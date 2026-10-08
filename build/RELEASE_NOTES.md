## BREKEM STUDIO 3.1.1

Descarga **BREKEM STUDIO 3.1.1 Setup.exe**, ábrelo e instala. Todo viene dentro del
instalador y funciona sin internet: Python y todas las librerías, FFmpeg, Praat y todos
los modelos de IA (Demucs `htdemucs_ft`, `htdemucs_6s` y `htdemucs`, DeepFilterNet3).

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
