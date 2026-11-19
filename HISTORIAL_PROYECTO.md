# Historial del proyecto Astra Pro, ROS 2 y ESP32

El proyecto comenzó con una prueba de recepción de coordenadas XYZ y llegó a una demostración de apertura automática por proximidad de un rostro. El trabajo se realizó localmente en Windows y Ubuntu 24.04 bajo WSL 2. La guía de operación y reproducción está en el [README](README.md) y los comandos de consola están en [COMANDOS.txt](COMANDOS.txt).

## 1. Verificación del entorno y lectura de profundidad

- Se identificaron dos interfaces USB independientes de la Astra Pro. OpenNI 2 abre el sensor de profundidad por su URI. DirectShow mostró el RGB de la Astra en el índice `1` de este equipo.
- La profundidad se verificó a **640 × 480 y 30 fps**, con muestras en unidades de **1 mm**. Dos capturas de 30 fotogramas produjeron **60 lecturas válidas** del píxel central `(320, 240)`. La exactitud absoluta de la distancia requiere una referencia independiente.
- El paquete Python de OpenNI usado en el primer intento omitía el número de serie en la estructura del dispositivo y el proceso fallaba al cerrar. Se pasó a la API C del SDK de Orbbec mediante `ctypes`, usando las estructuras del fabricante. Se verificaron dos cierres correctos, la lectura con relleno entre filas y el tratamiento de ceros y búferes truncados.
- Se confirmó ROS 2 **Jazzy**, `rclpy` y `geometry_msgs` en WSL, así como la detección del adaptador CP210x del ESP32 en **COM3**.

## 2. Publicación de XYZ en ROS 2

El nodo `astra_xyz` publica un `geometry_msgs/msg/PointStamped` en `/astra/xyz`. El marco `astra_depth_optical_frame` expresa los puntos en metros con X hacia la derecha, Y hacia abajo y Z hacia delante. El conversor OpenNI obtiene el punto 3D a partir del píxel y su profundidad. El sello corresponde a la recepción del fotograma en Windows y las muestras antiguas se descartan en WSL.

La primera prueba publicó el píxel central de la cámara y se comprobó con `ros2 topic echo /astra/xyz`. También se verificó el signo de X e Y usando puntos a ambos lados del centro. El tópico se usa para distribuir muestras a los suscriptores. El flujo implementado funciona sin servicios ROS 2.

## 3. Calibración RGB–depth con una caja

### Diagnóstico inicial

El SDK aceptó el registro nativo de profundidad a color. Al consultar los parámetros de fábrica de esta unidad mediante la extensión de Orbbec, devolvió valores `NaN`. Se compararon ambas orientaciones RGB y se comprobó con posiciones laterales de la caja que el RGB de DirectShow y el depth ya coincidían en el lado de la imagen. El visor conservó la **orientación original del RGB**.

En cuatro poses de la caja con registro nativo, el depth quedó **entre 3 y 16 px a la derecha** del RGB en los bordes laterales. En el borde superior, el desfase vertical fue de **0 a 2 px**. La variación entre poses motivó un ajuste proyectivo.

### Método de calibración

1. Se tomaron cuatro parejas de RGB y **depth crudo** con la caja en distintas poses. Se anotaron las cuatro esquinas de la misma cara en las dos imágenes.
2. Se ajustó un plano a los puntos 3D del interior de la cara usando las profundidades válidas de la Astra. Cada esquina 3D se recuperó al intersectar ese plano con el rayo de su píxel de depth. Esto permite estimarla aunque el borde tenga huecos.
3. Se estimó una matriz de proyección `P` de **3 × 4** con **transformación lineal directa normalizada (DLT)** y descomposición en valores singulares (SVD). Se usaron 12 esquinas de tres poses y se reservó la cuarta pose para evaluar.
4. Para proyectar un punto se calcula `[a, b, c]ᵀ = P · [X, Y, Z, 1]ᵀ`. Su píxel RGB predicho es `(a/c, b/c)`.

### Error de reproyección

El error de una esquina es la distancia entre la posición proyectada y la esquina observada en RGB. Con las diferencias horizontal y vertical en píxeles, se calcula `e = √(ΔX² + ΔY²)`. El RMS resume los errores de las cuatro esquinas mediante `√(Σe²/n)`.

| Comparación en la pose reservada | Error RMS | Error máximo |
|---|---:|---:|
| Superposición directa del depth crudo | 9,58 px | 13,42 px |
| Proyección con DLT | **4,72 px** | **6,12 px** |

El ajuste se comprobó también con una proyección sintética conocida y con el rechazo de puntos coplanares. La evaluación real cubre una pose reservada con esquinas anotadas manualmente. El modelo usado carece de un término explícito de distorsión. Para cuantificar una mejora frente al registro nativo se necesitan las mismas poses y referencias en ambos modos. La matriz y los errores por esquina están en el archivo local `resultados/calibracion_caja_evaluada.json`.

## 4. Visor en vivo y prueba por clic

El visor evolucionó de una comparación lado a lado a **una sola imagen RGB con profundidad superpuesta**. En modo de medición, el primer clic congela la imagen y marca el borde RGB. El segundo marca el mismo borde en depth. Se muestran `ΔX = u_depth − u_rgb`, `ΔY = v_depth − v_rgb` y la distancia total del par. La **mediana de los clics** resume la sesión de medición. El **RMS** de la tabla anterior resume la validación de la calibración.

En modo de envío manual, cada clic válido recupera el XYZ del píxel original del sensor de profundidad. Si varias muestras se proyectan sobre el mismo píxel RGB, se usa la más cercana. Se descartan huecos y se espera la confirmación de un ciclo antes de aceptar otro envío. La prueba interactiva registró **16 ciclos confirmados**. El primer clic confirmado correspondió a aproximadamente **(+0,231, +0,075, 0,851) m**.

## 5. Puente serial, firmware y MG995

El camino del dato quedó así:

```text
Astra Pro → visor en Windows → astra_xyz en WSL → /astra/xyz
→ esp32_bridge en WSL → COM3 en Windows → ESP32 → MG995
```

- El ESP32-WROOM-32 se programó con Arduino ESP32 **3.3.12**. COM3 opera a **115200 bit/s**. El servo recibe PWM por **GPIO18** y alimentación externa de **6,4 V**, con tierra común con el ESP32.
- El firmware comprueba el formato y la secuencia de cada orden. Responde `ACK` al aceptar la orden y `DONE` al completar los tiempos de movimiento. El protocolo mantiene una sola orden en curso.
- Durante la carga se mantuvo **BOOT** hasta que comenzó la escritura. Con BOOT suelto, un pulso de **EN/RESET** permitió iniciar el firmware cuando el ESP32 quedó sin responder al primer intento.
- En la primera prueba de extremo a extremo, un punto real de la Astra de aproximadamente **(0, 0, 1,063) m** produjo `DONE 1`. El giro y el retorno del MG995 se confirmaron visualmente. El ángulo exacto queda por medir.

## 6. Detección frontal y puerta simulada

La primera fase facial usa la cascada frontal de OpenCV. Detecta **cualquier rostro frontal** y utiliza el de mayor área si aparece más de uno. Se calcula XYZ en el centro del recuadro. Ante un hueco en el centro, se usa el píxel válido más próximo dentro de una ventana de **7 × 7**. Esta fase funciona sin identificación de personas.

El disparo ocurre con **Z ≤ 0,50 m** durante tres fotogramas consecutivos. El ESP32 ordena la apertura, espera **3 segundos**, ordena el retorno y emite `DONE` tras la pausa de retorno de **700 ms**. Para rearmar, el rostro se aleja a **0,60 m o más** o sale del encuadre durante al menos **0,8 s**. La comprobación incluye el umbral, el bloqueo de envíos repetidos y el rechazo de una profundidad inválida.

En vivo se registraron ciclos confirmados a **0,495 m**, **0,490 m** y **0,493 m**, con **3,726 a 3,760 s** entre la publicación y `DONE`. Ese tiempo incluye la apertura, el retorno y la comunicación. Tras reabrir el visor, se verificó otra activación a **0,478 m**. El modo facial se ejecuta con `--rostros` y la selección manual sigue disponible con `--enviar-ros`.

## Archivos para retomar el proyecto

| Archivo o carpeta | Contenido |
|---|---|
| [README.md](README.md) | Arquitectura, configuración, método de calibración, cableado y pruebas. |
| [COMANDOS.txt](COMANDOS.txt) | Comandos para abrir los modos del visor y observar el tópico en otra consola. |
| [docs/ROS2.md](docs/ROS2.md) | Contratos de mensajes y protocolo serial. |
| [diagnostico/](diagnostico/) | Captura, calibración, visor y detección de rostro. |
| [ros2/](ros2/) | Publicadores, modo interactivo y puente al ESP32. |
| [windows/serial_esp32.ps1](windows/serial_esp32.ps1) | Comunicación serial y validación de respuestas. |
| [firmware/astra_receptor/](firmware/astra_receptor/) | Recepción de coordenadas y control PWM. |
| `resultados/` | Matriz de calibración, capturas y registros locales de confirmación. |

La proyección experimental del visor necesita el archivo local `resultados/calibracion_caja_evaluada.json`. Esa carpeta está excluida por `.gitignore`. Al trasladar el proyecto hay que conservar la matriz de esta cámara o indicar su ubicación con `--calibracion`.
