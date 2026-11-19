# Integración ROS 2 Jazzy

El visor y los controladores de la Astra Pro se ejecutan en Windows. Los nodos ROS 2 se ejecutan en Ubuntu 24.04 bajo WSL 2. El proceso serial de Windows abre el adaptador CP210x del ESP32. El puerto observado en el montaje fue `COM3` a 115200 bit/s.

## Nodos y modos de operación

| Modo | Publicador `astra_xyz` | Suscriptor `esp32_bridge` |
|---|---|---|
| Diagnóstico continuo con `emitir_xyz.py --ros` | [astra_xyz.py](../ros2/astra_xyz.py) lee los puntos por entrada estándar y publica hasta cinco por segundo. | Se arranca por separado si se necesita accionar el servo. |
| Visor manual con `--enviar-ros` | [clic_xyz.py](../ros2/clic_xyz.py) publica un punto por selección válida. | Se inicia con el visor y transmite el comando `P`. |
| Visor facial con `--rostros` | [clic_xyz.py](../ros2/clic_xyz.py) publica un punto al cumplir el umbral y la persistencia. | Se inicia con el visor y transmite el comando `F`. |

El modo interactivo ejecuta ambos nodos en un mismo proceso de WSL. El mensaje pasa por el tópico ROS 2 antes de llegar al puente. La selección y la detección se hacen en Windows, y el visor intercambia datos con WSL por los canales estándar del proceso. La integración usa un tópico y prescinde de servicios y acciones ROS 2.

## Contrato de `/astra/xyz`

- Tipo `geometry_msgs/msg/PointStamped` y marco `astra_depth_optical_frame`.
- `point.x`, `point.y` y `point.z` en metros. X hacia la derecha, Y hacia abajo y Z hacia delante desde la cámara de profundidad.
- `header.stamp` representa la recepción del fotograma en Windows. El código compara ese sello con el reloj del sistema de WSL y admite una diferencia máxima de un segundo.
- Se descartan puntos con componentes no finitas o Z no positiva. El puente exige el marco óptico indicado.
- La profundidad de cola es 10 para el publicador y 1 para el suscriptor, con la política predeterminada de ROS 2 para publicación y suscripción. El modo interactivo también verifica que el sello recibido corresponda a la selección en curso.

## Contrato serial del ESP32

| Paso | Modo manual | Modo facial |
|---|---|---|
| Comprobación inicial | `HELLO ASTRA1` → `READY ASTRA1` | `HELLO ASTRA2` → `READY ASTRA2` |
| Orden | `P secuencia X Y Z` | `F secuencia X Y Z` |
| Firmware acepta | `ACK secuencia` | `ACK secuencia` |
| Firmware termina los tiempos PWM | `DONE secuencia` | `DONE secuencia` |

El [proceso serial](../windows/serial_esp32.ps1) valida ambas respuestas y la secuencia. Si falla la confirmación, se interrumpe la sesión de envío. El [firmware](../firmware/astra_receptor/astra_receptor.ino) marca el final de los tiempos programados con `DONE`. La posición angular real del servo requiere observación o medición independiente.

## Ver el sistema en ejecución

Desde Ubuntu, con el modo correspondiente iniciado según [COMANDOS.txt](../COMANDOS.txt):

```bash
source /opt/ros/jazzy/setup.bash
ros2 node list
ros2 node info /astra_xyz
ros2 node info /esp32_bridge
ros2 topic info /astra/xyz --verbose
ros2 topic echo /astra/xyz
```

En el visor, `echo` muestra una muestra por selección válida o disparo facial. Para observar una tasa continua, se usa el modo de diagnóstico y se ejecuta `ros2 topic hz /astra/xyz`. Los registros de confirmación del visor se guardan localmente en `resultados/visor/`. La configuración de cámara, calibración y cableado se describe en el [README](../README.md).
