## BREKEM STUDIO 3.4.0

**Dos instaladores. Escoge uno:**

- **Tienes tarjeta NVIDIA (GTX 16, RTX 20 / 30 / 40 / 50): edición GPU.** Descarga
  `BREKEM.STUDIO.3.4.0.GPU.Setup.exe` **y todos los archivos `.bin`** que tienen el mismo
  nombre, en una carpeta vacía. Abre el `.exe`: él solo usa los `.bin`.
- **No tienes NVIDIA: edición normal.** Descarga `BREKEM.STUDIO.3.4.0.Setup.exe`.

### Nuevo en 3.4: mucho más rápido, mismo sonido
- **Máster con referencias**: los intentos y la búsqueda del 6/6 son los mismos. Lo que sale
  igual en cada intento (afinación, limpieza de voz, beat, matchering, exciter, INSTRUMENTAL,
  ACAPELLA) se hace **una sola vez** por canción; los demás intentos solo prueban el tono.
- **Más canciones llegan a 6/6**: si la búsqueda normal se atasca en 5/6 porque un ajuste
  llegó a su tope (por ejemplo el aire a -8 dB), sigue con un rango más amplio y hasta 6
  intentos más. Las canciones que ya llegaban a 6/6 salen exactamente igual.
- **Matchering**: las referencias se procesan **todas a la vez**, una por núcleo del CPU.
- **Lote**: mientras una canción se masteriza en el CPU, la tarjeta NVIDIA ya va **separando
  la próxima**.
- **Estilos de máster**: varios a la vez (uno por cada dos hilos del CPU).
- FLAC y MP3 se codifican a la vez.
- **Continuar donde te quedaste** (Lote, Distribuir carpeta, Estilos carpeta): las canciones
  que ya están terminadas en la carpeta de salida se **saltan**. Las que quedaron a medias se
  hacen otra vez. Para rehacer una canción, borra su carpeta.

Todo viene dentro del instalador y funciona sin internet: Python y todas las librerías,
FFmpeg, Praat y todos los modelos de IA (Demucs `htdemucs_ft`, `htdemucs_6s` y `htdemucs`,
DeepFilterNet3).

### Nuevo en 3.3: usa tu tarjeta NVIDIA (CUDA)
- La edición GPU corre la **separación de stems (Demucs)** y la **limpieza de voz
  (DeepFilterNet)** en la tarjeta. Es la parte lenta: en el CPU tarda minutos por canción.
- En RTX 30 / 40 / 50 usa los **tensor cores** (TF32). No usa fp16, así que los stems
  salen con la misma calidad que en el CPU.
- Al abrir, el log dice qué tarjeta encontró y qué corre en ella, por ejemplo
  `GPU: NVIDIA GeForce RTX 4070 (12 GB, CUDA 12.8) - AI separation + vocal cleaning run on it`.
- Si la tarjeta no sirve (driver viejo, tarjeta muy vieja) o se queda sin memoria,
  todo sigue en el CPU, como antes, sin fallar.
- Necesita un **driver NVIDIA reciente** (2025 o más nuevo).

### Nuevo en 3.2: Exciter
- Marca **[X] Exciter** en Extras (en todas las pestañas). Crea **armónicos nuevos** a partir
  de la música misma, como un Aphex Aural Exciter arriba y un MaxxBass abajo, en vez de
  solo subir el EQ (que también sube el soplido):
  - **Agudos**: brillo y *air* (cerca de +1.3 dB arriba de 5 kHz). Se aguanta solo en las
    "S", así que no pone la voz áspera.
  - **Bajo**: armónicos del sub (70-200 Hz) para que el bajo **se oiga en celulares, laptops
    y audífonos** que no tocan el sub. Funciona hasta con un 808 limpio. No toca la zona
    del "mud" (250 Hz para arriba).
  - Solo suena donde hay música: el soplido en los silencios y en el final no sube.
- Va en MASTER, INSTRUMENTAL y todos los estilos, antes del guardián y del limitador: el
  volumen final es el mismo. La ACAPELLA no se toca.

### Arreglo en 3.1.2
- **Instalado en Program Files**: el MASTER con referencias fallaba con
  `PermissionError ... track_v2.log` porque el motor guardaba su registro dentro de la
  carpeta del programa, y Windows no deja escribir ahí sin ser administrador. Ahora todos los
  registros van a `%LOCALAPPDATA%\BrekemStudio\logs` y funciona esté donde esté instalado.
- Si un máster con referencias no sale, el log ahora lo dice claro (`!! ERROR`).
- **Referencias con símbolos** (`⧹`) o acentos: el programa instalado todavía se caía con
  `UnicodeEncodeError` al mostrar la comparación con las referencias (el arreglo de la 3.1.1
  solo funcionaba desde el código fuente). Ahora el propio programa escribe en UTF-8.

- **Volumen con referencias fuertes**: el MASTER siempre salía a -9.3 LUFS, así que con
  referencias más fuertes (reggaetón/pop a -8 o -7) fallaba el punto *loudness* y el
  programa no tenía cómo corregirlo. Ahora el volumen sigue a la referencia más suave
  (nunca más bajo que -9.3 ni más fuerte que -7.0, para no aplastarlo).

### Arreglos en 3.1.1
- **Masters con referencias**: el guardián de bandas ya no pelea con las referencias. Con
  referencias solo controla los picos y el tono lo deciden las referencias, así que el
  *air* y los graves por fin llegan al objetivo (antes un corte de -8 dB de air rebotaba).
- **Nombres con símbolos raros** (por ejemplo `⧹` en una referencia) ya no rompen la
  comparación con las referencias ni el veredicto x/6.
- **ACAPELLA suave** ahora llega a su volumen objetivo (-12 LUFS).

### 3.1: pestaña "Styles & Tune"
- Cualquier audio (archivo o carpeta) → **solo** lo que marques con [X]: los estilos de
  máster que quieras (Clarity, Punch, Espacial…) y/o la afinación natural.
- Con la afinación marcada saca **TUNED MIX.wav** (la canción con la voz afinada, nada más
  cambiado) y **ACAPELLA TUNED.wav**. Sin MASTER / INSTRUMENTAL / APPLE.

### 3.0: afinación natural (auto-tune sin robot)
- Marca **[X] Natural pitch correction** en Extras (en todas las pestañas).
- Lee la **tonalidad del beat** y mueve **cada nota completa** a la nota correcta: el
  centro de la nota queda afinado y se conservan **tu vibrato, tus deslices y tus
  subidas** dentro de la nota. Así suena natural, no robótico.
- Cambia el tono **sin cambiar el timbre** de la voz (PSOLA de Praat): nada de voz de
  ardilla ni metálica.
- Solo afina donde hay voz; el beat que se cuela en la pista de voz no se toca.
- En *Mix from stems* afina tu voz grabada a la tonalidad del beat.

### De la 2.0 (sigue todo)
- Separación en todos los stems (4 o 6), mezcla por partes.
- Final de las canciones arreglado (sin interferencia, sin sube y baja).
- 8 estilos de máster con su [X] y `COMPARE.html`.
- Bajo centrado y seco [X], guardián de bandas [X].
- 100% offline.

### Requisitos
Windows 10/11 de 64 bits. Unos 5 GB libres. La primera canción tarda más (prepara los modelos).
