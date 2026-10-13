## BREKEM STUDIO 3.1.2

Descarga **BREKEM STUDIO 3.1.2 Setup.exe**, ábrelo e instala. Todo viene dentro del
instalador y funciona sin internet: Python y todas las librerías, FFmpeg, Praat y todos
los modelos de IA (Demucs `htdemucs_ft`, `htdemucs_6s` y `htdemucs`, DeepFilterNet3).

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
