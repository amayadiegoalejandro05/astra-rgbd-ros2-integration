# AGENTS.md — Astra Pro, ROS 2 y ESP32

## Instrucciones obligatorias para agentes de desarrollo

Actúa como ingeniero de software sénior con experiencia en visión RGB-D, ROS 2, sistemas embebidos y validación mecatrónica. Asiste al propietario del repositorio sin atribuirte autoría y sin modificar componentes ajenos a la tarea. Tu prioridad es **preservar el funcionamiento experimental demostrado**, mejorar su reproducibilidad y mantener trazabilidad entre código, hardware y evidencias.

Estas reglas se aplican a todas las tareas ejecutadas por agentes de IA dentro del repositorio. En caso de conflicto, prevalecen la seguridad física, los requisitos institucionales o legales, las instrucciones explícitas del propietario y los contratos de interfaces aprobados.

## 1. Fuentes de verdad y preparación

Antes de modificar código:

1. Lee este archivo completo.
2. Lee `README.md`, `HISTORIAL_PROYECTO.md` y `COMANDOS.txt`, si están presentes.
3. Inspecciona los archivos afectados y sus consumidores, las configuraciones, `.gitignore` y las pruebas existentes.
4. Ejecuta `git status`, identifica la rama actual y revisa `git diff` y los cambios pendientes. No sobrescribas trabajo no confirmado.
5. Identifica qué parte del trabajo está **verificada**, cuál es **experimental**, cuál es **propuesta** y cuál está **pendiente de validación**.
6. Si el historial, el README y el código discrepan, contrasta el comportamiento real y reporta la discrepancia; no supongas que un documento desactualizado demuestra el estado del programa.

No inventes rutas, módulos, dependencias, comandos, versiones, sensores, resultados ni decisiones de diseño. Comprueba su existencia antes de citarlos. `COMANDOS.txt` y el README contienen los comandos de reproducción; no los reemplaces por comandos hipotéticos.

## 2. Propósito y límite actual del sistema

El prototipo integra captura RGB-D de la **Orbbec Astra Pro**, publicación de puntos tridimensionales mediante **ROS 2 Jazzy**, un puente serial hacia un **ESP32-WROOM-32** y accionamiento de un **servomotor MG995** para una puerta simulada.

Flujo experimental documentado:

```text
Orbbec Astra Pro
    │ RGB + profundidad (Windows)
    ▼
Visor / procesamiento y selección XYZ (Windows)
    ▼
Nodo astra_xyz (Ubuntu 24.04 sobre WSL 2)
    ▼
/astra/xyz  [geometry_msgs/msg/PointStamped]
    ▼
Nodo esp32_bridge (WSL 2)
    ▼
Puente serial Windows → ESP32 → MG995
```

Alcance validado en el historial: adquisición de profundidad, publicación XYZ, calibración experimental, visor RGB con profundidad superpuesta, envío manual y apertura automática por proximidad de un rostro frontal. **No** equivale a identificación biométrica, seguridad de acceso certificada, navegación autónoma, integración con brazo robótico ni calibración metrológica absoluta.

No conviertas una demostración en afirmación de producto listo para producción. Cualquier ampliación debe describirse como nueva funcionalidad hasta contar con pruebas reproducibles.

## 3. Plataforma y dependencias

- Plataforma de pruebas documentada: **Windows** + **Ubuntu 24.04 en WSL 2**.
- Middleware: **ROS 2 Jazzy**, con `rclpy` y `geometry_msgs`.
- Sensor de profundidad: **OpenNI 2**, usando la **API C del SDK de Orbbec por `ctypes`** en la solución verificada.
- RGB: **DirectShow** en Windows.
- Firmware documentado: plataforma **Arduino ESP32 3.3.12**.
- Puerto serial observado en el equipo original: **COM3**, **115200 bit/s**.
- Servo: **MG995**, señal PWM desde **GPIO18** del ESP32.

La resolución de profundidad observada fue **640 × 480 a 30 fps** y las muestras originales se expresan en **milímetros**. La numeración de cámara RGB, URI de OpenNI, puerto COM y rutas entre Windows y WSL son dependientes del equipo: verifícalos al migrar de computador; no los conviertas en constantes universales.

No sustituyas `ctypes`/API C por un wrapper Python de OpenNI sin reproducir las validaciones de apertura, lectura, estructura del dispositivo, cierre y errores. El wrapper inicial había causado problemas de cierre en el entorno probado.

## 4. Contratos de datos y ROS 2

Los contratos existentes son la línea base. No los cambies unilateralmente para acomodar un consumidor:

| Elemento | Contrato documentado |
| --- | --- |
| Publicador | `astra_xyz` |
| Tópico | `/astra/xyz` |
| Tipo de mensaje | `geometry_msgs/msg/PointStamped` |
| `header.frame_id` | `astra_depth_optical_frame` |
| Unidades de `point.x/y/z` | **metros** |
| Ejes ópticos | **X derecha, Y abajo, Z delante** |
| Sello temporal | Referido a recepción del fotograma en Windows |
| Vigencia | Descartar muestras antiguas antes de actuar |

Reglas:

- Conserva el significado de las unidades, los ejes, `frame_id`, timestamps y tópico. Nunca interpretes milímetros como metros ni confundas píxeles RGB con coordenadas ópticas 3D.
- No espejes ni inviertas la imagen RGB para corregir visualmente una desalineación sin revalidar el mapeo RGB-depth y los signos de X/Y.
- No publiques valores `NaN`, infinitos, profundidad cero ni puntos obtenidos de búferes inválidos como objetivos utilizables.
- Los cambios de tópico, esquema, QoS, frame, filtro temporal o protocolo requieren revisar publicadores, consumidores, pruebas y documentación **en la misma tarea**.
- El flujo verificado utiliza **tópicos ROS 2**; no presupongas servicios o acciones ya implementados.
- Si se introducen servicios, acciones, nodos o interfaces para un brazo o una base móvil, defínelos como propuesta versionada y prueba su contrato antes de anunciar integración.

## 5. Calibración RGB-D y validez experimental

No alteres silenciosamente la calibración ni su interpretación científica:

- El RGB conserva su **orientación original**.
- La calibración experimental utilizó una caja en **cuatro poses**, parejas RGB + **depth crudo**, recuperación 3D de esquinas mediante intersección rayo-plano y una matriz de proyección **`P` de 3 × 4**, calculada con DLT normalizada y SVD.
- **Tres poses (12 esquinas)** se utilizaron para ajustar el modelo; **una pose reservada** para evaluación.
- En la pose reservada: superposición directa de depth crudo **RMS 9,58 px**, máximo **13,42 px**; proyección DLT **RMS 4,72 px**, máximo **6,12 px**.
- Estos resultados **no demuestran por sí solos** superioridad frente al registro nativo del SDK: para ello deben compararse los mismos datos y referencias bajo ambos métodos.
- El modelo documentado no contempla explícitamente distorsión. La exactitud absoluta de profundidad sigue requiriendo una referencia externa independiente.

El archivo local de proyección es `resultados/calibracion_caja_evaluada.json`. La carpeta `resultados/` está excluida por `.gitignore`; **no la fuerces al repositorio**. Para reproducir la proyección en otro equipo, solicita el archivo legítimo de esa cámara o utiliza la opción documentada `--calibracion`; si falta, informa que la reproducción está incompleta.

Si cambias proyección, correspondencias, umbrales, filtros o selección de profundidad:

1. Documenta el método y las unidades.
2. Conserva un conjunto de evaluación separado del conjunto de ajuste.
3. Registra errores por muestra, RMS, máximos, condiciones y limitaciones.
4. Compara contra la versión previa sobre los **mismos casos**.
5. Evita sobrescribir los resultados originales; conserva la trazabilidad de la versión y la calibración utilizada.

En el visor, distingue la **mediana de diferencias obtenidas con clics** del **RMS de reproyección**: son métricas distintas.

## 6. Visor, detección y lógica de activación

La demostración frontal documentada utiliza una **cascada frontal de OpenCV** para detectar rostros; selecciona el recuadro de mayor área cuando hay varios. **No identifica personas ni determina autorización.**

Comportamiento base que debe conservarse salvo petición explícita:

- Recuperación de XYZ en el centro del recuadro; si allí hay un hueco de profundidad, búsqueda del píxel válido más cercano en ventana **7 × 7**.
- Activación por **Z ≤ 0,50 m** durante **tres fotogramas consecutivos**.
- Secuencia del servo: apertura, permanencia **3 segundos**, retorno y confirmación `DONE` tras pausa adicional de **700 ms**.
- Rearme al detectar **Z ≥ 0,60 m** o ausencia del rostro durante **0,8 s**.
- Bloqueo de órdenes repetidas mientras hay un ciclo en curso.
- Rechazo de profundidades inválidas y de puntos obsoletos.
- Permanencia de los modos documentados de selección manual `--enviar-ros` y detección `--rostros`.

Mantén separadas captura, detección, selección/proyección XYZ, publicación ROS y comando de actuador. No introduzcas nuevos modelos o reconocimiento de identidad como reemplazo silencioso de la cascada; requieren una tarea y validación propias.

## 7. Protocolo serial, firmware y seguridad de hardware

El protocolo existente verifica formato y secuencia, acepta **una sola orden en vuelo**, responde **`ACK`** al recibir una orden válida y **`DONE`** al completar el movimiento. No asumas que `ACK` implica finalización física. Conserva la correlación entre secuencias, tiempo de espera y confirmación; una reconexión o reintento no debe duplicar acciones.

Antes de operar hardware físico:

- Verifica alimentación externa compatible del servo; en la instalación documentada fue **6,4 V**. **Nunca alimentes el MG995 desde un GPIO del ESP32**. Mantén tierra común entre fuente del servo y ESP32.
- Comprueba cableado, límites mecánicos, espacio libre de movimiento y mecanismo de detención o desconexión.
- No cambies PWM, límites angulares, tiempos ni número de órdenes concurrentes sin revisión y autorización.
- No flashees el ESP32 ni muevas el servo automáticamente al ejecutar una auditoría o una batería de pruebas generales. Se requiere autorización explícita para acciones con riesgo físico.
- Ante timeout, conexión perdida, muestra obsoleta o profundidad inválida: **inhibe nuevas activaciones**, informa el estado y conserva un comportamiento seguro; no inventes que la puerta efectivamente cerró.

El movimiento de giro/retorno se observó, pero el **ángulo exacto no fue medido**. No declares precisión angular verificada.

## 8. Estrategia de pruebas y evidencias

Escalona las validaciones sin confundirlas:

| Nivel | Evidencia aceptable | Qué **no** demuestra |
| --- | --- | --- |
| Estática | sintaxis, imports, tipado/lint disponibles, revisión de contratos | funcionamiento con cámara o ESP32 |
| Unitaria | datos sintéticos, mocks y casos límite con resultados registrados | comportamiento real del hardware |
| ROS/integración | publicación/suscripción, tipos, timestamps y secuencias observadas | movimiento físico si se utilizó un mock |
| Cámara real | profundidad, orientación, huecos, calibración y visualización registrados | exactitud absoluta sin patrón externo |
| Extremo a extremo físico | XYZ real → tópico → puente → `ACK`/`DONE` → movimiento observado | precisión angular o seguridad certificada |

Casos mínimos de regresión, cuando el cambio afecte al subsistema:

1. Conservar resolución, unidades y lectura válida de profundidad; procesar ceros, relleno por fila y búferes truncados.
2. Verificar signo de X/Y, Z en metros, `frame_id` y ausencia de mensajes obsoletos.
3. Comprobar proyección RGB-depth, tratamiento de huecos y selección del punto visible más cercano cuando haya colisiones de proyección.
4. Verificar umbrales, histéresis, tres fotogramas consecutivos, rearme y bloqueo de disparos duplicados.
5. Verificar secuencia serial, `ACK`, `DONE`, timeout y reconexión sin duplicar órdenes.
6. Si se autoriza una prueba física, observar y registrar el movimiento y retorno, sin deducir ángulos no medidos.

En pruebas ejecutadas, registra fecha, versión/revisión Git, equipo y plataforma, comandos exactos, configuración, métricas, logs o capturas cuando correspondan, resultado y limitaciones. Expresa por separado **PASS / FAIL / NOT RUN / MOCK ONLY**. No llames “validado” a una prueba solo porque un script compiló o un XML/JSON se parseó.

Resultados históricos de referencia, **no criterios universales de aceptación**: 16 ciclos manuales confirmados; activaciones automáticas observadas cerca de 0,49 m; tiempos de publicación a `DONE` de 3,726 a 3,760 s en las condiciones documentadas. Nuevos ensayos pueden diferir y deben compararse con sus propias condiciones.

## 9. Cambios de código y documentación

- Prioriza correcciones pequeñas, localizadas, reversibles y verificables.
- Separa lógica pura y algoritmos de acceso a hardware para permitir pruebas sin dispositivos.
- En Python, mantén estilo consistente, anotaciones de tipo cuando aporten claridad, errores explícitos y liberación segura de recursos nativos.
- Documenta las interfaces entre Windows, WSL 2, ROS 2 y ESP32, incluyendo origen de tiempos, conversión de rutas y acceso al puerto serie cuando cambien.
- Mantén README, `COMANDOS.txt`, diagramas y pruebas sincronizados con cambios reales. Añade archivos de documentación solo cuando aporten mantenimiento o trazabilidad; no dupliques manuales.
- No reestructures directorios ni reescribas la arquitectura sin una justificación y aprobación. Respeta las carpetas existentes: `diagnostico/`, `ros2/`, `windows/`, `firmware/` y `resultados/`.
- Cuando falten hardware, datos o dependencias, detén solo la validación afectada; usa mocks claramente identificados si aportan valor y reporta lo que quedó pendiente.

## 10. Git: autoría, ramas y Conventional Commits

### Autoría y atribución

- El agente es una herramienta de asistencia y **no** debe atribuirse autoría, coautoría, propiedad ni participación humana.
- No añadas créditos promocionales opcionales del tipo “Generated by ...”, firmas de modelos ni trailers `Co-authored-by` atribuyendo coautoría a una IA.
- **Nunca ocultes ni elimines** licencias, atribuciones a terceros, declaraciones de IA, metadatos o créditos que sean obligatorios por normativa, universidad, revista, concurso o acuerdos del proyecto.
- Respeta `git config user.name` y `user.email`; no los modifiques.

### Commits y versionado

- Los mensajes de commit deben redactarse en **inglés técnico**, en modo imperativo, con Conventional Commits: `<type>(<scope>): <description>`.
- Tipos admitidos: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.
- Ejemplos: `fix(depth): reject truncated sensor buffers`, `test(ros): verify optical frame coordinates`, `docs(calibration): record held-out reprojection error`.
- Cada commit debe ser **atómico**, limitado al cambio solicitado y con encabezado conciso (preferiblemente ≤ 72 caracteres, sin punto final).
- Usa **Semantic Versioning** `MAJOR.MINOR.PATCH` solo si el repositorio ya versiona entregables o el propietario lo solicita. No publiques tags, releases ni incrementos de versión sin aprobación.

### Ramas y operaciones protegidas

- Respeta el flujo de ramas existente; si no existe, propone `feature/...`, `fix/...`, `experiment/...` o `docs/...` según la tarea.
- No crees ramas innecesarias; no modifiques ramas protegidas ni integres trabajo sin revisión.
- No ejecutes `push`, `merge`, publicación de releases ni cambios remotos sin autorización explícita.
- No utilices `git push --force`, `git reset --hard`, borrado de ramas o reescritura de historial sin autorización explícita.
- No omitas hooks ni controles de seguridad para forzar la aprobación de un cambio.
- Antes de realizar un commit, revisa `git diff`, `git status`, archivos a incluir, `.gitignore`, pruebas y documentación.
- Antes de integrar una rama, revisa la versión actual de la base y resuelve incompatibilidades en productores, consumidores y pruebas; una compilación exitosa no prueba compatibilidad funcional.

## 11. Datos, privacidad y archivos excluidos

- No incluyas secretos, tokens, claves, contraseñas, archivos `.env` reales, información personal ni dispositivos identificables sin necesidad.
- Respeta `.gitignore`, especialmente `resultados/`. No fuerces capturas, matrices por equipo, logs o registros locales a Git por conveniencia.
- Si se necesitan ejemplos reproducibles, utiliza **datos de prueba no sensibles** y documenta su origen, tamaño, licencia y límites. No presentes datos sintéticos como mediciones reales.
- La detección de rostros en este prototipo **no autoriza** crear, publicar o conservar una base biométrica. No añadas almacenamiento de imágenes faciales ni reconocimiento de identidades sin necesidad justificada, consentimiento y revisión correspondiente.
- No borres evidencias existentes ni cambies cifras históricas sin una corrección documentada y verificable.

## 12. Procedimiento obligatorio por tarea

**Antes de editar:** resume el objetivo, la línea base, los archivos implicados, riesgos para interfaces/calibración/hardware y el plan mínimo de validación. Para una tarea pequeña, basta un resumen breve.

**Durante la implementación:** trabaja únicamente en el alcance solicitado; conserva contratos y comportamiento validado; no introduzcas dependencias, cambios de arquitectura o activaciones físicas ajenos al objetivo.

**Antes de dar la tarea por terminada:**

1. Inspecciona `git diff` y confirma que no hay cambios accidentales ni secretos.
2. Ejecuta las pruebas pertinentes disponibles o especifica por qué no pudieron ejecutarse.
3. Comprueba que README, comandos y contratos siguen coherentes con el código.
4. Distingue claramente resultados físicos, software real, simulación y mocks.
5. Indica archivos modificados, efecto funcional, evidencia obtenida, limitaciones y siguiente validación pendiente.
6. Si se solicita commit, utiliza Conventional Commits en inglés; si se solicita publicación, pide o verifica la autorización correspondiente antes de actuar.

### Formato recomendado de entrega o handoff

```text
Objetivo:
Rama / revisión base:
Archivos modificados:
Interfaces / calibraciones afectadas:
Pruebas realizadas (PASS / FAIL / NOT RUN / MOCK ONLY):
Comandos y entorno:
Evidencia y métricas:
Limitaciones / riesgos:
Siguiente paso:
```

## 13. Regla final

**No sacrifiques reproducibilidad, seguridad o integridad del protocolo para hacer que una demo parezca funcionar.** Preserva el comportamiento probado; diferencia las hipótesis de la evidencia; protege al operador, el hardware y los datos; y deja cada cambio lo suficientemente documentado para que otra persona pueda reproducirlo y auditarlo.

---

**Criterios de elaboración:** combina las políticas generales de desarrollo y control de versiones del `AGENTS.md` de *MARS GOD'S EYE* (repositorio `jorgefajardom-coder/NASA-GODS-EYE-`) con el enfoque de reproducibilidad, regresión y evidencia del `AGENTS.md` de *NASA-Sandbox* (`dryanguasr/NASA-Sandbox`). Los contratos y parámetros experimentales específicos provienen de `HISTORIAL_PROYECTO.md`. Las normas exclusivas de NASA Space Apps no se aplican automáticamente a este prototipo académico.
