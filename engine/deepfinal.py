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
"""LIMPIEZA PROFUNDA de todo el catalogo + PASE FINAL (match Bad Bunny), en un solo proceso.
Por tema:
  A) sacar el original del zip -> decode 48k
  B) demucs htdemucs (voz / instrumental)
  C) limpiar la VOZ: DeepFilterNet3 (ruido/sala) + de-breath + de-plosive, re-nivelada a su RMS
  D) mezcla = voz_limpia + instrumental
  E) libmaster (curva 3 refs)
  F) pase final: expansion adaptativa + pulido + bbmatch (balance BB) + loudnorm -9.5 / TP -1.1
  G) QC
Los ~21 del lote reciente ya venian limpios: se saltan A-E y se les hace solo F desde su master.
Resumible: si ya existe MASTER FINAL/<name> se salta. Borra stems/intermedios por tema (disco).
"""
import os, re, sys, json, glob, shutil, zipfile, subprocess, numpy as np, soundfile as sf, scipy.signal as sig, librosa

SP = _HOME
DL = _WORK
MAST = os.path.join(_WORK, "_masters")
DSTD = os.path.join(_WORK, "_out")
WORK = _WORK
STEMS = _STEMS
LOG  = os.path.join(SP, "deepfinal.log")
SR   = 48000
os.makedirs(DSTD, exist_ok=True); os.makedirs(WORK, exist_ok=True); os.makedirs(STEMS, exist_ok=True)

BB_LOW, BB_PRES, BB_AIR = 19.6, -9.35, -19.15
LRA_TARGET = 5.5

ALREADY_CLEAN = {  # lote reciente ya limpiado con clean_master.py -> solo pase final
 "Chicle master.wav","donde estan v 6 master.wav","una ves y otra ves master.wav",
 "poderoso 2 master.wav","Si me sale v2 master.wav","fumando 5 master.wav",
 "somo enemigos v2 master.wav","Mejor de lo que doy master.wav","Brekem - sin coro master.wav",
 "Piedra ft power walker v2 master.wav","triste me siento v2 master.wav","CM master.wav",
 "Muriendo Mi primera cancion master.wav","Pa encima master.wav","Brekem - Jesucristo es master.wav",
 "BUSCA LA CHAMPANA 16 octubre master.wav","armamento v2 master.wav",
 "JAQUE MATE- UN PAL DE COSAS FT BREKEM master.wav","muchos dicen v4 master.wav",
 "Veo ft Power Walker v2 master.wav","sin importar oct 12 master.wav",
}

def run(c): return subprocess.run(c, capture_output=True, text=True)
def rms(x): return float(np.sqrt(np.mean(x**2))+1e-12)
def load(p):
    x,s=sf.read(p,dtype="float64",always_2d=True)
    if x.shape[1]==1: x=np.repeat(x,2,1)
    if s!=SR:
        g=np.gcd(int(s),SR); x=sig.resample_poly(x,SR//g,s//g,axis=0)
    return x
def slog(m):
    with open(LOG,"a",encoding="utf-8") as f: f.write(m+"\n")
    print(m,flush=True)

# ---------- DeepFilterNet (una sola vez) ----------
import types as _t
_fake=_t.ModuleType("torchaudio.backend.common")
class AudioMetaData:
    def __init__(self,sample_rate=0,num_frames=0,num_channels=0,bits_per_sample=0,encoding="PCM_S"):
        self.sample_rate=sample_rate;self.num_frames=num_frames;self.num_channels=num_channels
        self.bits_per_sample=bits_per_sample;self.encoding=encoding
_fake.AudioMetaData=AudioMetaData
sys.modules["torchaudio.backend.common"]=_fake
import torchaudio as _ta
if not hasattr(_ta,"backend"):
    _b=_t.ModuleType("torchaudio.backend");_b.common=_fake
    sys.modules["torchaudio.backend"]=_b;_ta.backend=_b
from df.enhance import enhance, init_df
import torch
_DFN_MB = os.environ.get("BREKEM_DFN_MODEL")
_DFM,_DFS,_=init_df(model_base_dir=_DFN_MB) if (_DFN_MB and os.path.isdir(_DFN_MB)) else init_df()

def deepfilter(voc,n):
    vt=torch.from_numpy(np.ascontiguousarray(voc.T)).float()
    vt=enhance(_DFM,_DFS,vt,atten_lim_db=10.0)
    return vt.cpu().numpy().T.astype(np.float64)[:n]

def debreath(voc,n):
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
    gB=np.ones(n); fade=int(0.02*SR); at=10**(-18/20)
    for a,b in mb:
        s=max(0,int(a/fps*SR)-fade//2); e=min(n,int(b/fps*SR)+fade//2)
        r=0.5-0.5*np.cos(np.linspace(0,np.pi,min(fade,e-s)))
        seg=np.full(e-s,at,float); seg[:len(r)]=1-(1-at)*r; seg[-len(r):]=np.minimum(seg[-len(r):],1-(1-at)*r[::-1])
        gB[s:e]=np.minimum(gB[s:e],seg)
    return voc*gB[:,None], len(mb)

def deplosive(voc,n):
    vd=voc.mean(1)
    def edb(x,w=12):
        k=int(w*SR/1000); return 20*np.log10(np.sqrt(np.convolve(x**2,np.ones(k)/k,mode="same"))+1e-9)
    lf=edb(sig.sosfilt(sig.butter(4,[25/(SR/2),80/(SR/2)],btype="band",output="sos"),vd))
    hf=edb(sig.sosfilt(sig.butter(4,[300/(SR/2),4000/(SR/2)],btype="band",output="sos"),vd))
    fbnd=edb(sig.sosfilt(sig.butter(2,120/(SR/2),btype="high",output="sos"),vd),40)
    lfm=sig.medfilt(lf[::64],2*int((SR/64)//2)+1); lfm=np.interp(np.arange(n),np.arange(0,n,64)[:len(lfm)],lfm)
    dom=lf-hf
    hot=(lf>lfm+14)&(lf>np.percentile(lf,75))&(dom>np.median(dom)+12)&(lf>fbnd-4)
    pl=[]; i=0
    while i<n:
        if hot[i]:
            j=i
            while j<n and hot[j]: j+=1
            pl.append([i,j]); i=j
        else: i+=1
    pl=[p for p in pl if int(0.03*SR)<=p[1]-p[0]<=int(0.35*SR)]
    mp=[]
    for a,b in pl:
        if mp and a-mp[-1][1]<0.08*SR: mp[-1][1]=b
        else: mp.append([a,b])
    pl=mp
    hp=sig.butter(4,110/(SR/2),btype="high",output="sos"); pad=int(0.06*SR); f2=int(0.02*SR)
    for a,b in pl:
        s=max(0,a-pad); e=min(n,b+pad); m=np.ones(e-s)
        r=0.5-0.5*np.cos(np.linspace(0,np.pi,min(f2,(e-s)//2))); m[:len(r)]=r; m[-len(r):]=r[::-1]
        for c in range(2):
            ch=voc[s:e,c]; voc[s:e,c]=ch*(1-m)+sig.sosfilt(hp,ch)*10**(-3/20)*m
    return voc, len(pl)

# ---------- pase final (igual que masterfinal.py) ----------
_KW_SOS=np.array([[1.53512485958697,-2.69169618940638,1.19839281085285,1.0,-1.69065929318241,0.73248077421585],
                  [1.0,-2.0,1.0,1.0,-1.99004745483398,0.99007225036621]])   # ITU-R BS.1770 K-weighting @48k
def kweight(x):
    # real loudness weighting. It used to be a 1.5 kHz high-pass, so the expanders
    # followed hi-hats and the vocal, not loudness: the level dropped every time the
    # vocal stopped (outros, song tails) and came back with the next hat -> pumping.
    return sig.sosfilt(_KW_SOS,x)
def macro_expand(x,ratio,lo=-3.0,hi=2.0,win=3.0,smooth_hz=0.12):
    """slow, gentle upward/downward expansion on short-term loudness (3 s, K-weighted),
    zero-phase smoothed so the gain drifts between sections instead of riding every
    bar. Range clipped to lo..hi dB: a fade-out or a quiet tail just sits at `lo`
    (constant gain) instead of being pushed down and pulled back up."""
    mono=x.mean(1); w=int(win*SR); hop=int(0.1*SR); kw=kweight(mono); n=len(mono)
    if n<w+8*hop: return x
    env=np.array([10*np.log10(np.mean(kw[i:i+w]**2)+1e-12) for i in range(0,n-w+1,hop)])
    centre=np.percentile(env,55)
    g=np.clip((env-centre)*min(ratio-1.0,0.35),lo,hi)
    g=sig.sosfiltfilt(sig.butter(2,smooth_hz/(SR/hop/2),btype="low",output="sos"),g)
    tsamp=np.arange(n); tenv=np.arange(len(g))*hop+w//2
    return x*(10**(np.interp(tsamp,tenv,g)/20.0))[:,None]
def bq_peak(x,f0,g_db,Q):
    A=10**(g_db/40);w0=2*np.pi*f0/SR;al=np.sin(w0)/(2*Q);c=np.cos(w0)
    b=np.array([1+al*A,-2*c,1-al*A]);a=np.array([1+al/A,-2*c,1-al/A])
    return sig.lfilter(b/a[0],a/a[0],x,axis=0)
def bq_shelf(x,f0,g_db,hi_shelf,S=0.7):
    A=10**(g_db/40);w0=2*np.pi*f0/SR;c=np.cos(w0)
    al=np.sin(w0)/2*np.sqrt((A+1/A)*(1/S-1)+2);sq=2*np.sqrt(A)*al
    if hi_shelf:
        b=[A*((A+1)+(A-1)*c+sq),-2*A*((A-1)+(A+1)*c),A*((A+1)+(A-1)*c-sq)]
        a=[(A+1)-(A-1)*c+sq,2*((A-1)-(A+1)*c),(A+1)-(A-1)*c-sq]
    else:
        b=[A*((A+1)-(A-1)*c+sq),2*A*((A-1)-(A+1)*c),A*((A+1)-(A-1)*c-sq)]
        a=[(A+1)+(A-1)*c+sq,-2*((A-1)+(A+1)*c),(A+1)+(A-1)*c-sq]
    b=np.array(b);a=np.array(a)
    return sig.lfilter(b/a[0],a/a[0],x,axis=0)
def polish(x):
    x=sig.sosfilt(sig.butter(2,24/(SR/2),btype="high",output="sos"),x,axis=0)
    mid=(x[:,0]+x[:,1])*0.5; side=(x[:,0]-x[:,1])*0.5
    side=side-sig.sosfilt(sig.butter(4,120/(SR/2),btype="low",output="sos"),side)
    x=np.stack([mid+side,mid-side],axis=1)
    x=bq_peak(x,280,-1.2,1.0)
    band=sig.sosfilt(sig.butter(4,[6000/(SR/2),8500/(SR/2)],btype="band",output="sos"),x.mean(1))
    k=int(0.012*SR); e=np.sqrt(np.convolve(band**2,np.ones(k)/k,mode="same"))
    edb=20*np.log10(e+1e-9); thr=np.percentile(edb,92)
    red=np.clip((edb-thr)*0.6,0,2.5); g=10**(-red/20)
    a=np.exp(-1.0/(0.005*SR)); g=sig.lfilter([1-a],[1,-a],g)
    xn=sig.sosfilt(sig.butter(4,[5000/(SR/2),9500/(SR/2)],btype="band",output="sos"),x,axis=0)
    return x-xn*(1-g)[:,None]
def bands_arr(x):
    m=x.mean(1); f,P=sig.welch(m,SR,nperseg=8192)
    def bd(lo,hi):
        s=(f>=lo)&(f<hi); return 10*np.log10(np.mean(P[s])+1e-12)
    r=bd(200,2000); L,R=x[:,0],x[:,1]
    corr=float(np.sum(L*R)/(np.sqrt(np.sum(L**2)*np.sum(R**2))+1e-12))
    return bd(30,120)-r, bd(2000,6000)-r, bd(8000,16000)-r, corr
def bbmatch(y):
    mid=(y[:,0]+y[:,1])*0.5; side=(y[:,0]-y[:,1])*0.5*0.88
    y=np.stack([mid+side,mid-side],axis=1)
    blo,bpr,bair,_=bands_arr(y)
    y=bq_shelf(y,90,float(np.clip(BB_LOW-blo,-2.5,4.0)),False)
    y=bq_peak (y,3800,float(np.clip(BB_PRES-bpr,-2.0,4.0)),0.7)
    y=bq_shelf(y,11000,float(np.clip(BB_AIR-bair,-3.0,5.0)),True)
    return y
def ebur(p):
    s=run(["ffmpeg","-hide_banner","-nostats","-i",p,"-af","ebur128=framelog=quiet:peak=true","-f","null","-"]).stderr.split("Summary:")[-1]
    def g(k,u):
        m=re.search(k+r":\s*(-?[\d.]+)\s*"+u,s); return float(m.group(1)) if m else None
    return g("I","LUFS"),g("LRA","LU"),g("Peak","dBFS")
def meas(p):
    j=run(["ffmpeg","-hide_banner","-i",p,"-af","loudnorm=I=-9.5:TP=-1.0:LRA=11:print_format=json","-f","null","-"]).stderr
    a=j.rfind("{"); b=j.rfind("}"); return json.loads(j[a:b+1])

def vbus(voc):
    """MEZCLA: procesado de bus de voz -> HPF, de-ess, compresion, presencia/aire."""
    voc=sig.sosfilt(sig.butter(2,90/(SR/2),btype="high",output="sos"),voc,axis=0)
    # de-ess (sidechain 5.5-9 kHz)
    sc=sig.sosfilt(sig.butter(4,[5500/(SR/2),9000/(SR/2)],btype="band",output="sos"),voc.mean(1))
    k=int(0.006*SR); e=np.sqrt(np.convolve(sc**2,np.ones(k)/k,mode="same")); edb=20*np.log10(e+1e-9)
    thr=np.percentile(edb,90); red=np.clip((edb-thr)*0.7,0,4.0); g=10**(-red/20)
    a=np.exp(-1.0/(0.003*SR)); g=sig.lfilter([1-a],[1,-a],g)
    de=sig.sosfilt(sig.butter(4,[5000/(SR/2),10000/(SR/2)],btype="band",output="sos"),voc,axis=0)
    voc=voc-de*(1-g)[:,None]
    # compresion de voz  ~2.5:1
    mono=voc.mean(1); b=np.exp(-1.0/(0.015*SR))
    env=np.sqrt(sig.lfilter([1-b],[1,-b],mono**2)+1e-12); envdb=20*np.log10(env+1e-9)
    thr=np.percentile(envdb,75)-2.0
    over=np.maximum(envdb-thr,0.0); gr=-over*(1-1/2.5)
    aA=np.exp(-1.0/(0.005*SR)); aR=np.exp(-1.0/(0.12*SR))
    out=np.zeros_like(gr); prev=0.0
    for i,v in enumerate(gr):
        c=aA if v<prev else aR; prev=c*prev+(1-c)*v; out[i]=prev
    voc=voc*(10**(out/20))[:,None]*10**(2.0/20)   # makeup ~+2 dB
    # presencia + aire de voz
    voc=bq_peak(voc,4000,1.5,0.8)
    voc=bq_shelf(voc,12000,1.5,True)
    return voc

def glue(mix):
    """MEZCLA: compresion de bus (glue) ~1.5:1, 1-2 dB."""
    mono=mix.mean(1); k=int(0.03*SR)
    env=np.sqrt(np.convolve(mono**2,np.ones(k)/k,mode="same")); edb=20*np.log10(env+1e-9)
    thr=np.percentile(edb,80); over=np.maximum(edb-thr,0.0); gr=-over*(1-1/1.5)
    a=np.exp(-1.0/(0.05*SR)); gr=sig.lfilter([1-a],[1,-a],gr)
    return mix*(10**(gr/20))[:,None]

def deep_clean(orig_path, base):
    """A-E -> devuelve ruta a un wav 'cleaned master' (curva 3 refs), o None."""
    tag=base.replace(" ","_")[:60]
    sd=os.path.join(STEMS,tag)
    vc=os.path.join(sd,"vocals.flac"); ic=os.path.join(sd,"no_vocals.flac")
    if os.path.exists(vc) and os.path.exists(ic):
        voc=load(vc); inst=load(ic)                      # cache hit -> sin demucs
    else:
        src=os.path.join(WORK,tag+"_src.wav")
        run(["ffmpeg","-hide_banner","-y","-i",orig_path,"-ar","48000","-ac","2","-c:a","pcm_s24le",src])
        if not os.path.exists(src): return None,0,0
        sep=os.path.join(WORK,"sep")
        run([_PYEXE, "-m", "demucs","--two-stems","vocals","-n","htdemucs","-o",sep,src])
        sepdir=os.path.join(sep,"htdemucs",os.path.splitext(os.path.basename(src))[0])
        vp=os.path.join(sepdir,"vocals.wav"); ip=os.path.join(sepdir,"no_vocals.wav")
        if not os.path.exists(vp):
            try: os.remove(src)
            except: pass
            return None,0,0
        os.makedirs(sd,exist_ok=True)
        run(["ffmpeg","-hide_banner","-y","-i",vp,"-c:a","flac","-sample_fmt","s32","-compression_level","8",vc])
        run(["ffmpeg","-hide_banner","-y","-i",ip,"-c:a","flac","-sample_fmt","s32","-compression_level","8",ic])
        voc=load(vc if os.path.exists(vc) else vp); inst=load(ic if os.path.exists(ic) else ip)
        try: shutil.rmtree(sepdir)
        except: pass
        try: os.remove(src)
        except: pass
    n=min(len(voc),len(inst)); voc,inst=voc[:n],inst[:n]
    r0=rms(voc)
    voc=deepfilter(voc,n)
    voc,nb=debreath(voc,n)
    voc,npl=deplosive(voc,n)
    # MEZCLA: bus de voz + balance voz/pista (voz un pelin al frente) + glue
    voc=vbus(voc)
    voc*=(r0/rms(voc))*10**(1.0/20)
    mix=glue(voc+inst)
    pk=np.max(np.abs(mix));
    if pk>0.99: mix*=0.99/pk
    pre=os.path.join(WORK,tag+"_clean.wav"); sf.write(pre,mix.astype(np.float32),SR,subtype="PCM_24")
    s1=os.path.join(WORK,tag+"_s1.wav")
    run([_PYEXE, os.path.join(_HOME, "libmaster.py"),pre,s1])
    cleaned = s1 if os.path.exists(s1) else pre
    # limpieza de disco (los stems quedan cacheados en STEMS)
    try: os.remove(pre)
    except: pass
    return cleaned,nb,npl

def final_pass(cleaned_arr, name):
    out=os.path.join(DSTD,name)
    t0=os.path.join(WORK,"f0.wav"); sf.write(t0,cleaned_arr.astype(np.float32),SR,subtype="PCM_24")
    _,lra0,_=ebur(t0); l0=lra0 or 0
    x=cleaned_arr
    if l0<7.0:
        deficit=min(max(LRA_TARGET-l0,0),4.0)
        x=macro_expand(x,ratio=1.30+deficit*0.34)
    x=polish(x)
    pk=np.max(np.abs(x)); x=x*(0.995/pk) if pk>0.995 else x
    t1=os.path.join(WORK,"f1.wav"); sf.write(t1,x.astype(np.float32),SR,subtype="PCM_24")
    t2=os.path.join(WORK,"f2.wav")
    if os.path.exists(t2): os.remove(t2)
    run([_PYEXE, os.path.join(_HOME, "libmaster.py"),t1,t2])
    y=load(t2 if os.path.exists(t2) else t1)
    y=bbmatch(y)
    pk=np.max(np.abs(y)); y=y*(0.995/pk) if pk>0.995 else y
    t3=os.path.join(WORK,"f3.wav"); sf.write(t3,y.astype(np.float32),SR,subtype="PCM_24")
    # ---- loudness/limitador deterministico (loudnorm dinamico no alcanza el objetivo
    #      cuando la fuente esta muy baja; usamos gain estatico + comp + limitador true-peak 4x)
    I3,_,_=ebur(t3)
    if I3 is None: I3=-14.0
    # sin compresor de bus aqui: aplastaba el LRA que macro_expand recupero.
    # solo gain estatico + limitador true-peak 4x oversampling.
    gain=float(np.clip(-8.0-I3,0.0,14.0))
    af=(f"volume={gain:.2f}dB,"
        f"aresample=192000:resampler=soxr:precision=28,"
        f"alimiter=limit=0.87:level=0:asc=1,"
        f"aresample=48000:resampler=soxr:precision=28,"
        f"alimiter=limit=0.945:level=0")
    ra=run(["ffmpeg","-hide_banner","-y","-i",t3,"-af",af,"-ar","48000","-c:a","pcm_s24le",out])
    if ra.returncode!=0 or not os.path.exists(out): return None
    I,L,T=ebur(out)
    if I is not None and abs(I-(-9.3))>0.6:
        g2=float(np.clip(-9.3-I,-3.0,3.0))
        t4=os.path.join(WORK,"f4.wav")
        r2=run(["ffmpeg","-hide_banner","-y","-i",out,"-af",
                f"volume={g2:.2f}dB,aresample=192000:resampler=soxr,alimiter=limit=0.87:level=0:asc=1,"
                f"aresample=48000:resampler=soxr,alimiter=limit=0.945:level=0",
                "-ar","48000","-c:a","pcm_s24le",t4])
        if r2.returncode==0 and os.path.exists(t4):
            os.replace(t4,out); I,L,T=ebur(out)
    lo,pr,air,corr=bands_arr(load(out))
    return I,L,T,lo,pr,air,corr

# @@BREKEM_HELPERS_END@@  (acap_pro execs everything above this line)

# ---------- match table ----------
mt={}
for ln in open(os.path.join(SP,"match_table.tsv"),encoding="utf-8"):
    p=ln.rstrip("\n").split("\t")
    if len(p)==3: mt[p[0]]=(p[1],p[2])
ZP={os.path.basename(z):z for z in [
    os.path.join(DL,"MI MUSICA.zip"),
    os.path.join(DL,"mi musica-20260828T235455Z-1-001.zip"),
    os.path.join(DL,"mi musica-20260828T235455Z-1-002.zip")]}

if os.path.exists(LOG): os.replace(LOG,LOG+".prev")
masters=sorted(glob.glob(os.path.join(MAST,"*.wav")))
_only=os.environ.get("DF_ONLY","")
if _only: masters=[m for m in masters if _only.lower() in os.path.basename(m).lower()]
_lim=int(os.environ.get("DF_LIMIT","0"))
if _lim: masters=masters[:_lim]
slog(f"{len(masters)} temas  |  limpieza profunda + pase final BB -> {DSTD}\n")
rows=[]
for i,mp in enumerate(masters,1):
    name=os.path.basename(mp); out=os.path.join(DSTD,name)
    if os.path.exists(out):
        I,L,T=ebur(out); lo,pr,air,corr=bands_arr(load(out))
        rows.append([name,I,L,T,lo,pr,air,True,"ya"]); slog(f"[{i}/{len(masters)}] {name}  (ya hecho)  I={I} LRA={L} TP={T}"); continue
    try:
        if name in ALREADY_CLEAN:
            arr=load(mp); tagc="F"
            nb=npl=-1
        else:
            if name not in mt:
                slog(f"[{i}/{len(masters)}] {name}  SIN ORIGINAL -> pase final desde master");
                arr=load(mp); tagc="F(sinorig)"; nb=npl=-1
            else:
                zpn,entry=mt[name]; zpath=ZP.get(zpn)
                ex=os.path.join(WORK,"in_"+re.sub(r'[^A-Za-z0-9.]+','_',os.path.basename(entry)))
                with zipfile.ZipFile(zpath) as zf, open(ex,"wb") as g:
                    g.write(zf.read(entry))
                base=re.sub(r"\s*master\.wav$","",name)
                cleaned,nb,npl=deep_clean(ex,base)
                try: os.remove(ex)
                except: pass
                if cleaned is None:
                    slog(f"[{i}/{len(masters)}] {name}  FALLO clean -> pase final desde master"); arr=load(mp); tagc="F(failclean)"; nb=npl=-1
                else:
                    arr=load(cleaned); tagc="DEEP"
                    try: os.remove(cleaned)
                    except: pass
        res=final_pass(arr,name)
        if res is None:
            slog(f"[{i}/{len(masters)}] {name}  FALLO final"); rows.append([name,None,None,None,None,None,None,False,tagc]); continue
        I,L,T,lo,pr,air,corr=res
        ok=(T is not None and T<=-0.8) and (-12<=I<=-8) and (L is not None and L>=2.3)
        rows.append([name,I,L,T,lo,pr,air,ok,tagc])
        slog(f"[{i}/{len(masters)}] {name}  [{tagc}] breath={nb} plos={npl}\n   I={I} LRA={L} TP={T}  low{lo:+.1f} pres{pr:+.1f} air{air:+.1f} corr{corr:+.2f}  {'OK' if ok else 'REVISAR'}")
    except Exception as e:
        slog(f"[{i}/{len(masters)}] {name}  ERROR {e}")
        rows.append([name,None,None,None,None,None,None,False,"err"])

slog("\n==================  ANALISIS FINAL  ==================")
def stat(p):
    I,L,T=ebur(p); lo,pr,air,corr=bands_arr(load(p)); return I,L,T,lo,pr,air,corr
for nm,fn in [("BB Titi","bb_titi.wav"),("BB MONACO","bb_monaco.wav"),
              ("ref baticano","ref_baticano.wav"),("ref mayores","mayores.wav"),("ref despacito","despacito.wav")]:
    try:
        I,L,T,lo,pr,air,corr=stat(os.path.join(SP,fn))
        slog(f"  {nm:13s} I={I} LRA={L} TP={T}  low{lo:+.1f} pres{pr:+.1f} air{air:+.1f} corr{corr:+.2f}")
    except Exception as e: slog(f"  {nm}: {e}")
good=[r for r in rows if r[7]]; bad=[r for r in rows if not r[7]]
def col(rs,k): return [r[k] for r in rs if r[k] is not None]
if good:
    Is,Ls,Ts=col(good,1),col(good,2),col(good,3); los,prs,airs=col(good,4),col(good,5),col(good,6)
    slog(f"\n  MASTER FINAL  ({len(good)}/{len(rows)} distribuibles)")
    slog(f"    I medio {np.mean(Is):+.2f} LUFS ({min(Is):.1f}..{max(Is):.1f})   LRA medio {np.mean(Ls):.2f} LU ({min(Ls):.1f}..{max(Ls):.1f})")
    slog(f"    TP medio {np.mean(Ts):+.2f} dBFS (peor {max(Ts):+.2f})   low {np.mean(los):+.1f}  pres {np.mean(prs):+.1f}  air {np.mean(airs):+.1f}")
    ndeep=sum(1 for r in rows if r[8]=='DEEP')
    slog(f"    limpieza profunda aplicada: {ndeep}   |   solo pase final: {len(rows)-ndeep}")
if bad:
    slog("\n  REVISAR:")
    for r in bad: slog(f"    {r[0]}  I={r[1]} LRA={r[2]} TP={r[3]}  [{r[8]}]")
slog("\nLISTO")
