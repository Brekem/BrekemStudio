# --- BREKEM STUDIO path shim (injected) ---
import os as _os, sys as _sys, glob as _glob
_HOME  = _os.environ.get("BREKEM_HOME")  or _os.path.dirname(_os.path.abspath(__file__))
_WORK  = _os.environ.get("BREKEM_WORK")  or _os.path.join(_HOME, "_work")
_STEMS = _os.environ.get("BREKEM_STEMS") or _os.path.join(_HOME, "_stems")
_REFSD = _os.environ.get("BREKEM_REFS")  or _os.path.join(_HOME, "refs")
_PYEXE = _os.environ.get("BREKEM_PY")    or _sys.executable
for _d in (_WORK, _STEMS, _REFSD):
    try: _os.makedirs(_d, exist_ok=True)
    except Exception: pass
def _reflist():
    fs = sorted(_glob.glob(_os.path.join(_REFSD, "*.wav")) + _glob.glob(_os.path.join(_REFSD, "*.flac")))
    return fs
def _refdict():
    return {_os.path.splitext(_os.path.basename(f))[0]: f for f in _reflist()}
# --- end shim ---
"""Cadena ACAPELLA 'pro' (sin plugins de pago):
  deepfilter -> debreath(-9dB) -> deplosive_gated -> DEREVERB espectral
  -> EQ sustractiva (HPF85 / -2.5dB@400 / -2dB@3.2k) -> vbus -> match RMS
  -> plate sutil (pedalboard, ~9% wet) -> loud_to(-12 LUFS / -1.0 dBTP)

Uso:
  python acap_pro.py cojelo            -> solo cojelo, a "COJELO REALEASE/cojelo - ACAPELLA (pro).wav"
  python acap_pro.py ALL               -> regenera TODAS las acapellas con stems, in-place en ACAPELLAS/
                                          (respalda las viejas en ACAPELLAS_v1/)
"""
import os, re, sys, glob, shutil, numpy as np, soundfile as sf, scipy.signal as sig

SP = _HOME
exec(open(os.path.join(SP, "deepfinal.py"), encoding="utf-8").read().split("# @@BREKEM_HELPERS_END@@")[0])
import librosa
from pedalboard import Pedalboard, Reverb, HighpassFilter, PeakFilter, Gain

MF = os.path.join(_WORK, "_out")
DAC = os.path.join(_WORK, "_acap")
BKP = os.path.join(_WORK, "_acap_bkp")
CJ = os.path.join(_WORK, "_cj")
LOG  = os.path.join(SP, "acap_pro.log")
def L(m):
    open(LOG, "a", encoding="utf-8").write(m + "\n"); print(m, flush=True)

MODE = sys.argv[1] if len(sys.argv) > 1 else "cojelo"

# ---------- de-breath parametrizable ----------
def debreath_at(voc, n, at_db=-9.0):
    vm=voc.mean(1); hop,win=128,1024
    env=20*np.log10(librosa.feature.rms(y=vm,frame_length=win,hop_length=hop)[0]+1e-9)
    env=sig.medfilt(env,2*max(1,int(0.025*SR/hop))+1)
    cent=librosa.feature.spectral_centroid(y=vm,sr=SR,n_fft=win,hop_length=hop)[0][:len(env)]
    Ln=len(env); fps=SR/hop
    nf=np.percentile(env,10); P=np.percentile(env[env>nf+8],60); gap_thr,sing_thr=P-12,P-9
    lowm=env<gap_thr; gaps=[]; i=0
    while i<Ln:
        if lowm[i]:
            j=i
            while j<Ln and lowm[j]: j+=1
            if (j-i)/fps>=0.20: gaps.append((max(0,i-int(0.4*fps)),min(Ln,j+int(0.4*fps))))
            i=j
        else: i+=1
    dmin,dmax=int(0.09*fps),int(0.48*fps); br=[]
    for a,b in gaps:
        seg=env[a:b]; lmin=np.percentile(seg,10)
        cand=(env[a:b]>lmin+5)&(env[a:b]<sing_thr)&(cent[a:b]>1500)&(cent[a:b]<6000)
        i=0
        while i<len(cand):
            if cand[i]:
                j=i
                while j<len(cand) and cand[j]: j+=1
                if dmin<=j-i<=dmax and env[a+i:a+j].max()>=lmin+6 and env[a+i:a+j].max()<=sing_thr: br.append((a+i,a+j))
                i=j
            else: i+=1
    br.sort(); mb=[]
    for a,b in br:
        if mb and a-mb[-1][1]<0.06*fps: mb[-1][1]=b
        else: mb.append([a,b])
    gB=np.ones(n); fade=int(0.02*SR); at=10**(at_db/20)
    for a,b in mb:
        s=max(0,int(a/fps*SR)-fade//2); e=min(n,int(b/fps*SR)+fade//2)
        r=0.5-0.5*np.cos(np.linspace(0,np.pi,min(fade,e-s)))
        seg=np.full(e-s,at,float); seg[:len(r)]=1-(1-at)*r; seg[-len(r):]=np.minimum(seg[-len(r):],1-(1-at)*r[::-1])
        gB[s:e]=np.minimum(gB[s:e],seg)
    return voc*gB[:,None], len(mb)

def deplosive_gated(voc, n):
    vd = voc.mean(1)
    def edb(x, w=12):
        k = max(1, int(w*SR/1000))
        return 20*np.log10(np.sqrt(np.convolve(x**2, np.ones(k)/k, mode="same")) + 1e-9)
    lo_b  = sig.sosfilt(sig.butter(4,[25/(SR/2),75/(SR/2)],   btype="band", output="sos"), vd)
    mid_b = sig.sosfilt(sig.butter(4,[350/(SR/2),3500/(SR/2)],btype="band", output="sos"), vd)
    lf = edb(lo_b, 10); mf = edb(mid_b, 10)
    step = 256
    lfm = sig.medfilt(lf[::step], 2*int((SR/step*0.75)//1)+1)
    lfm = np.interp(np.arange(n), np.arange(0, n, step)[:len(lfm)], lfm)
    w_on = int(0.008*SR); d = np.zeros(n)
    d[w_on:] = lf[w_on:] - lf[:-w_on]
    dom = lf - mf
    hot = ((lf > lfm + 16) & (lf > np.percentile(lf, 88)) &
           (dom > np.median(dom) + 14) & (d > 9))
    pl=[]; i=0
    while i<n:
        if hot[i]:
            j=i
            while j<n and hot[j]: j+=1
            pl.append([i,j]); i=j
        else: i+=1
    pl=[p for p in pl if int(0.02*SR) <= p[1]-p[0] <= int(0.18*SR)]
    mp=[]
    for a,b in pl:
        if mp and a-mp[-1][1] < 0.06*SR: mp[-1][1]=b
        else: mp.append([a,b])
    pl=mp
    if not pl: return voc, 0
    low = sig.sosfilt(sig.butter(2, 100/(SR/2), btype="low", output="sos"), voc, axis=0)
    pad=int(0.025*SR); f2=int(0.012*SR); att=10**(-9/20); mask=np.zeros(n)
    for a,b in pl:
        s=max(0,a-pad); e=min(n,b+pad); m=np.ones(e-s)
        r=0.5-0.5*np.cos(np.linspace(0,np.pi,min(f2,(e-s)//2)))
        if len(r): m[:len(r)]=r; m[-len(r):]=r[::-1]
        mask[s:e]=np.maximum(mask[s:e], m)
    voc = voc - (1.0-att)*low*mask[:,None]
    return voc, len(pl)

# ---------- de-reverb espectral (spectral subtraction de la cola tardia) ----------
def dereverb(x, strength=0.55, tail_ms=110, floor=0.06):
    npr, nov = 2048, 1536
    hop_s = (npr - nov) / SR
    d = max(1, int((tail_ms / 1000) / hop_s))
    a = 0.62
    out = np.zeros_like(x)
    for c in range(x.shape[1]):
        f, t, Z = sig.stft(x[:, c], SR, window="hann", nperseg=npr, noverlap=nov,
                           boundary="zeros", padded=True)
        mag = np.abs(Z); ph = np.angle(Z)
        rev = np.zeros_like(mag)
        for k in range(1, mag.shape[1]):
            rev[:, k] = a * rev[:, k-1] + (1 - a) * mag[:, k-1]
        rev = np.roll(rev, d, axis=1); rev[:, :d] = 0.0
        m = np.maximum(mag - strength * rev, floor * mag)
        _, y = sig.istft(m * np.exp(1j*ph), SR, window="hann", nperseg=npr, noverlap=nov,
                         boundary=True)
        n0 = min(len(y), x.shape[0])
        out[:n0, c] = y[:n0]
    return out

# ---------- EQ sustractiva + plate (pedalboard) ----------
_EQ = Pedalboard([
    HighpassFilter(cutoff_frequency_hz=85.0),
    PeakFilter(cutoff_frequency_hz=400.0,  gain_db=-2.5, q=1.1),   # resonancia nasal de la separacion
    PeakFilter(cutoff_frequency_hz=3200.0, gain_db=-2.0, q=1.4),   # aspereza
])
_PLATE = Pedalboard([
    Reverb(room_size=0.32, damping=0.62, wet_level=0.09, dry_level=0.93, width=0.9),
    Gain(gain_db=0.0),
])
def eq_sub(x):   return _EQ(x.astype(np.float32), SR).astype(np.float64)
def plate(x):    return _PLATE(x.astype(np.float32), SR).astype(np.float64)

def loud_to(src, out, Itgt, tp_lin, drive=0.90):
    I3,_,_=ebur(src); I3 = I3 if I3 is not None else -14.0
    gain=float(np.clip(Itgt-1.0-I3, -12.0, 14.0))
    af=(f"volume={gain:.2f}dB,aresample=192000:resampler=soxr:precision=28,"
        f"alimiter=limit={drive}:level=0:asc=1,aresample=48000:resampler=soxr:precision=28,"
        f"alimiter=limit={tp_lin}:level=0")
    r=run(["ffmpeg","-hide_banner","-y","-i",src,"-af",af,"-ar","48000","-c:a","pcm_s24le",out])
    if r.returncode!=0 or not os.path.exists(out): return None
    I,Lr,T=ebur(out)
    if I is not None and abs(I-Itgt)>0.4:
        g2=float(np.clip(Itgt-I,-4.0,4.0)); tt=os.path.join(WORK,"ap_l.wav")
        r2=run(["ffmpeg","-hide_banner","-y","-i",out,"-af",
                f"volume={g2:.2f}dB,aresample=192000:resampler=soxr,alimiter=limit={drive}:level=0:asc=1,"
                f"aresample=48000:resampler=soxr,alimiter=limit={tp_lin}:level=0",
                "-ar","48000","-c:a","pcm_s24le",tt])
        if r2.returncode==0 and os.path.exists(tt): os.replace(tt,out); I,Lr,T=ebur(out)
        try: os.remove(tt)
        except: pass
    return ebur(out)

def build_one(vc, out, tagshow):
    voc=load(vc); n=len(voc); r0=rms(voc)
    voc=deepfilter(voc,n)
    voc,nb=debreath_at(voc,n,at_db=-9.0)
    voc,npl=deplosive_gated(voc,n)
    voc=dereverb(voc)
    voc=eq_sub(voc)
    voc=vbus(voc)
    rr=rms(voc); voc = voc*(r0/rr) if rr>0 else voc
    voc=plate(voc)
    pk=np.max(np.abs(voc)); voc = voc*(0.98/pk) if pk>0.98 else voc
    p0=os.path.join(WORK,"ap_a0.wav"); sf.write(p0,voc.astype(np.float32),SR,subtype="PCM_24")
    res=loud_to(p0,out,Itgt=-12.0,tp_lin=0.891,drive=0.89)
    I,La,Ta = res if res else (None,None,None)
    L(f"  {tagshow:34} breath={nb:3}  plos={npl}  I={I:6.1f} LRA={La:4.1f} TP={Ta:5.1f}")
    try: os.remove(p0)
    except: pass

if __name__ == "__main__" and MODE.lower() == "cojelo":
    L("=== acap_pro: cojelo ===")
    vc=os.path.join(STEMS,"cojelo_master_v2.wav","vocals.flac")
    build_one(vc, os.path.join(CJ,"cojelo - ACAPELLA (pro).wav"), "cojelo - ACAPELLA (pro)")
    L("LISTO acap_pro cojelo")
elif __name__ == "__main__":
    os.makedirs(BKP, exist_ok=True)
    fs=sorted(glob.glob(os.path.join(MF,"*.wav")))
    L(f"=== acap_pro: ALL ({len(fs)} temas) ===")
    done=miss=0
    for i,mp in enumerate(fs,1):
        name=os.path.basename(mp)
        tag=re.sub(r"\s*master\.wav$","",name).replace(" ","_")[:60]
        vc=os.path.join(STEMS,tag,"vocals.flac")
        if not os.path.exists(vc): miss+=1; continue
        oA=os.path.join(DAC,name)
        if os.path.exists(oA) and not os.path.exists(os.path.join(BKP,name)):
            shutil.copy2(oA, os.path.join(BKP,name))
        try:
            build_one(vc, oA, f"[{i:3}] {name[:28]}")
            done+=1
        except Exception as e:
            L(f"  [{i:3}] FALLO {name}: {e}")
    L(f"\nacap_pro ALL: hechas={done}  sin_stems={miss}")
    L("LISTO acap_pro ALL")
