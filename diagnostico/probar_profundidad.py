"""Comprueba la adquisición de profundidad de una Astra mediante OpenNI 2."""

import argparse
from contextlib import ExitStack, contextmanager
import ctypes as c
from pathlib import Path
from statistics import median
import sys


# Estructuras de OniCTypes.h de Orbbec OpenNI 2.3.0.86, Win64.
class DeviceInfo(c.Structure):
    _fields_ = [
        ("uri", c.c_char * 256), ("vendor", c.c_char * 256),
        ("name", c.c_char * 256), ("serialNumber", c.c_char * 256),
        ("usbVendorId", c.c_uint16), ("usbProductId", c.c_uint16),
    ]


class VideoMode(c.Structure):
    _fields_ = [
        ("pixelFormat", c.c_int), ("resolutionX", c.c_int),
        ("resolutionY", c.c_int), ("fps", c.c_int),
    ]


class Frame(c.Structure):
    _fields_ = [
        ("dataSize", c.c_int), ("data", c.c_void_p), ("sensorType", c.c_int),
        ("timestamp", c.c_uint64), ("frameIndex", c.c_int),
        ("width", c.c_int), ("height", c.c_int), ("videoMode", VideoMode),
        ("croppingEnabled", c.c_int), ("cropOriginX", c.c_int),
        ("cropOriginY", c.c_int), ("stride", c.c_int),
    ]


def cargar_api(sdk):
    api = c.CDLL(str(sdk / "OpenNI2.dll"))
    handle = c.c_void_p
    dispositivo = c.POINTER(DeviceInfo)
    fotograma = c.POINTER(Frame)
    # Firmas de OniCAPI.h. Los handles son punteros de 64 bits.
    firmas = {
        "oniInitialize": (c.c_int, c.c_int),
        "oniShutdown": (None,),
        "oniGetExtendedError": (c.c_char_p,),
        "oniGetDeviceList": (c.c_int, c.POINTER(dispositivo), c.POINTER(c.c_int)),
        "oniReleaseDeviceList": (c.c_int, dispositivo),
        "oniDeviceOpen": (c.c_int, c.c_char_p, c.POINTER(handle)),
        "oniDeviceClose": (c.c_int, handle),
        "oniDeviceIsImageRegistrationModeSupported": (c.c_int, handle, c.c_int),
        "oniDeviceSetProperty": (c.c_int, handle, c.c_int, c.c_void_p, c.c_int),
        "oniDeviceCreateStream": (c.c_int, handle, c.c_int, c.POINTER(handle)),
        "oniStreamSetProperty": (c.c_int, handle, c.c_int, c.c_void_p, c.c_int),
        "oniStreamDestroy": (None, handle),
        "oniStreamStart": (c.c_int, handle),
        "oniStreamStop": (None, handle),
        "oniWaitForAnyStream": (c.c_int, c.POINTER(handle), c.c_int, c.POINTER(c.c_int), c.c_int),
        "oniStreamReadFrame": (c.c_int, handle, c.POINTER(fotograma)),
        "oniFrameRelease": (None, fotograma),
        "oniCoordinateConverterDepthToWorld": (
            c.c_int, handle, c.c_float, c.c_float, c.c_float,
            c.POINTER(c.c_float), c.POINTER(c.c_float), c.POINTER(c.c_float),
        ),
    }
    for nombre, (retorno, *argumentos) in firmas.items():
        funcion = getattr(api, nombre)
        funcion.restype = retorno
        funcion.argtypes = argumentos
    return api


def verificar(api, operacion, estado):
    if estado:
        detalle = (api.oniGetExtendedError() or b"").decode(errors="replace").strip()
        raise RuntimeError(f"{operacion} (estado {estado}). {detalle}".strip())


def configurar_registro(api, camara, flujo, registrar=False):
    # Propiedades MIRRORING (7) e IMAGE_REGISTRATION (5) de OniCProperties.h.
    espejo = c.c_int(0)
    verificar(api, "Quitar espejo depth", api.oniStreamSetProperty(
        flujo, 7, c.byref(espejo), c.sizeof(espejo)))
    if registrar and not api.oniDeviceIsImageRegistrationModeSupported(camara, 1):
        raise RuntimeError("Este sensor no anuncia registro depth→RGB")
    modo = c.c_int(registrar)
    verificar(api, "Fijar modo de registro", api.oniDeviceSetProperty(
        camara, 5, c.byref(modo), c.sizeof(modo)))


@contextmanager
def flujo_profundidad(api, preparar=None):
    # ExitStack libera los recursos en orden inverso incluso si falla la captura.
    with ExitStack() as recursos:
        verificar(api, "Inicializar OpenNI", api.oniInitialize(2003))
        recursos.callback(api.oniShutdown)

        dispositivos = c.POINTER(DeviceInfo)()
        total = c.c_int()
        verificar(api, "Enumerar OpenNI", api.oniGetDeviceList(c.byref(dispositivos), c.byref(total)))
        try:
            if total.value != 1:
                raise RuntimeError(f"Se esperaba un dispositivo OpenNI, se encontraron {total.value}")
            info = dispositivos[0]
            uri = info.uri
            print(f"Dispositivo: {info.vendor.decode(errors='replace')} {info.name.decode(errors='replace')}")
            print(f"URI: {uri.decode(errors='replace')}")
        finally:
            api.oniReleaseDeviceList(dispositivos)

        camara, flujo = c.c_void_p(), c.c_void_p()
        verificar(api, "Abrir cámara", api.oniDeviceOpen(uri, c.byref(camara)))
        recursos.callback(api.oniDeviceClose, camara)
        # ONI_SENSOR_DEPTH = 3. Esta selección no depende del índice RGB.
        verificar(api, "Crear flujo de profundidad", api.oniDeviceCreateStream(camara, 3, c.byref(flujo)))
        recursos.callback(api.oniStreamDestroy, flujo)
        if preparar is not None:
            preparar(api, camara, flujo)
        verificar(api, "Iniciar flujo de profundidad", api.oniStreamStart(flujo))
        recursos.callback(api.oniStreamStop, flujo)
        yield flujo


@contextmanager
def leer_fotograma(api, flujo):
    listo = c.c_int()
    verificar(api, "Esperar fotograma (máximo 2 s)",
              api.oniWaitForAnyStream(c.byref(flujo), 1, c.byref(listo), 2000))
    fotograma = c.POINTER(Frame)()
    verificar(api, "Leer fotograma", api.oniStreamReadFrame(flujo, c.byref(fotograma)))
    try:
        yield fotograma.contents
    finally:
        api.oniFrameRelease(fotograma)


def capturar(api, muestras):
    validas = []
    with flujo_profundidad(api) as flujo:
        for muestra in range(muestras):
            with leer_fotograma(api, flujo) as frame:
                z_mm = medir_centro(frame, informar_modo=muestra == 0)
                if z_mm > 0:
                    validas.append(z_mm)
    return validas


def medir_centro(frame, informar_modo):
    # Formatos de profundidad métrica de OniCEnums.h.
    escala = {100: 1.0, 101: 0.1}.get(frame.videoMode.pixelFormat)
    if escala is None:
        raise RuntimeError(f"Formato de profundidad no métrico: {frame.videoMode.pixelFormat}")

    # El paso de fila incluye relleno. Cada píxel ocupa dos bytes.
    x, y = frame.width // 2, frame.height // 2
    desplazamiento = y * frame.stride + 2 * x
    if (
        frame.width < 1 or frame.height < 1
        or frame.stride % 2 or frame.stride < 2 * frame.width
        or not frame.data or desplazamiento + 2 > frame.dataSize
    ):
        raise RuntimeError("Buffer de profundidad incompatible con el fotograma")
    if informar_modo:
        print(f"Modo: {frame.width}x{frame.height}, {frame.videoMode.fps} fps, "
              f"{escala:g} mm/unidad. Píxel central: ({x}, {y})")
    return c.c_uint16.from_address(frame.data + desplazamiento).value * escala


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True, help="Carpeta de OpenNI2.dll")
    parser.add_argument("--muestras", type=int, default=30)
    args = parser.parse_args()
    if args.muestras < 1:
        parser.error("--muestras debe ser mayor que cero")
    sdk = args.sdk.resolve()
    if not (sdk / "OpenNI2.dll").is_file():
        parser.error(f"No se encontró OpenNI2.dll en {sdk}")
    if sys.platform != "win32" or c.sizeof(c.c_void_p) != 8:
        parser.error("Se requiere Python de 64 bits en Windows")

    try:
        validas = capturar(cargar_api(sdk), args.muestras)
    except (OSError, RuntimeError) as error:
        print(f"Error de diagnóstico: {error}", file=sys.stderr)
        return 1

    print(f"Muestras válidas: {len(validas)}/{args.muestras}")
    if not validas:
        print("El píxel central no devolvió profundidad válida.", file=sys.stderr)
        return 2
    print(f"Z mediana: {median(validas):.1f} mm, rango: {min(validas):.1f} a {max(validas):.1f} mm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
