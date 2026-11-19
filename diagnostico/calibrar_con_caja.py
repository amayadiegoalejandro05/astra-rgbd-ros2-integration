"""Estima y valida una proyección experimental de depth crudo a RGB."""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def normalizar(puntos):
    # Normalización isotrópica para que metros y píxeles no sesguen el ajuste.
    centro = puntos.mean(axis=0)
    dimension = puntos.shape[1]
    radio = np.mean(np.linalg.norm(puntos - centro, axis=1))
    if not np.isfinite(radio) or radio <= 0:
        raise ValueError("Los puntos no permiten calcular una escala válida")
    escala = np.sqrt(dimension) / radio
    matriz = np.eye(dimension + 1)
    matriz[:dimension, :dimension] *= escala
    matriz[:dimension, -1] = -escala * centro
    return (puntos - centro) * escala, matriz


def ajustar_proyeccion(xyz, uv):
    if len(xyz) < 8 or np.linalg.matrix_rank(xyz - xyz.mean(axis=0)) < 3:
        raise ValueError("Se necesitan puntos 3D repartidos en varias poses no coplanares")
    xyz_n, tf_xyz = normalizar(xyz)
    uv_n, tf_uv = normalizar(uv)
    hom = np.column_stack((xyz_n, np.ones(len(xyz_n))))
    sistema = np.zeros((2 * len(xyz_n), 12))
    sistema[0::2, :4] = hom
    sistema[1::2, 4:8] = hom
    sistema[0::2, 8:] = -hom * uv_n[:, :1]
    sistema[1::2, 8:] = -hom * uv_n[:, 1:]
    _, valores, vectores = np.linalg.svd(sistema, full_matrices=False)
    if valores[-2] < valores[0] * 1e-5:
        raise ValueError("Las poses no determinan una proyección estable")
    proyeccion = np.linalg.solve(tf_uv, vectores[-1].reshape(3, 4)) @ tf_xyz
    proyeccion /= np.linalg.norm(proyeccion[2, :3])
    if proyeccion[2, 2] < 0:
        proyeccion = -proyeccion
    return proyeccion


def proyectar(p, xyz):
    numerador = xyz @ p[:, :3].T + p[:, 3]
    if np.any(numerador[:, 2] <= 0):
        raise ValueError("La proyección ubica puntos detrás de la cámara RGB")
    return numerador[:, :2] / numerador[:, 2:3]


def rayos(uv, k):
    fx, fy, cx, cy = k
    xy = (uv - (cx, cy)) / (fx, fy)
    return np.column_stack((xy, np.ones(len(uv))))


def cargar_pose(raiz, pose, k):
    carpeta = raiz / pose["carpeta"]
    meta = json.loads((carpeta / "captura.json").read_text(encoding="utf-8"))
    if meta["registro_nativo_activado"] or meta["rgb_invertido_horizontalmente"]:
        raise ValueError("La calibración requiere depth crudo y RGB original")
    depth = cv2.imdecode(np.frombuffer((carpeta / "depth_mm.png").read_bytes(), np.uint8),
                         cv2.IMREAD_UNCHANGED)
    if depth is None or depth.shape != (480, 640) or depth.dtype != np.uint16:
        raise ValueError("Se esperaba depth métrico 640×480 de 16 bits")
    u0, v0, u1, v1 = pose["roi_depth"]
    if not (0 <= u0 < u1 <= 640 and 0 <= v0 < v1 <= 480):
        raise ValueError("La región interior de la caja está fuera de la imagen")
    z = depth[v0:v1, u0:u1]
    rango = z[z > 0]
    if len(rango) < 30:
        raise ValueError("La cara de la caja tiene muy poca profundidad válida")
    mediana = float(np.median(rango))
    yy, xx = np.where((z > 0) & (np.abs(z.astype(float) - mediana) <= 35))
    uv = np.column_stack((xx + u0, yy + v0))
    if len(uv) < 30:
        raise ValueError("Muy pocos píxeles pertenecen a la cara frontal")
    puntos = rayos(uv, k) * z[yy, xx, None] / 1000

    # Ajustar el plano de la cara. Las esquinas se obtienen al cortar sus rayos
    # con ese plano, porque el propio borde puede contener huecos o fondo.
    centro = puntos.mean(axis=0)
    _, _, vectores = np.linalg.svd(puntos - centro, full_matrices=False)
    normal = vectores[-1]
    esquinas_depth = np.asarray(pose["esquinas_depth"], dtype=float)
    esquinas_rgb = np.asarray(pose["esquinas_rgb"], dtype=float)
    if esquinas_depth.shape != (4, 2) or esquinas_rgb.shape != (4, 2):
        raise ValueError("Se requieren cuatro esquinas correspondientes por vista")
    for esquinas in (esquinas_depth, esquinas_rgb):
        if not np.all((0 <= esquinas) & (esquinas < (640, 480))):
            raise ValueError("Las esquinas deben estar dentro de la imagen")
    direcciones = rayos(esquinas_depth, k)
    incidencia = direcciones @ normal
    if not np.all(np.abs(incidencia) > 1e-6):
        raise ValueError("El plano es casi paralelo a un rayo de esquina")
    distancia = (centro @ normal) / incidencia
    if not np.all(np.isfinite(distancia) & (distancia > 0)):
        raise ValueError("La intersección de las esquinas con el plano es inválida")
    return direcciones * distancia[:, None], esquinas_rgb


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("anotaciones", type=Path)
    parser.add_argument("salida", type=Path, help="Ruta nueva para el informe JSON")
    args = parser.parse_args()
    datos = json.loads(args.anotaciones.read_text(encoding="utf-8"))
    k = np.asarray(datos["intrinsecos_depth_fx_fy_cx_cy"], dtype=float)
    if k.shape != (4,) or not np.isfinite(k).all() or min(k[:2]) <= 0:
        parser.error("Intrínsecos depth inválidos")
    poses = datos["poses"]
    if len(poses) < 4 or not poses[-1].get("validacion") or any(p.get("validacion") for p in poses[:-1]):
        parser.error("Incluye al menos tres poses para ajuste y una última pose separada para validar")
    muestras = [cargar_pose(args.anotaciones.parent, pose, k) for pose in poses]
    xyz, uv = (np.concatenate(partes) for partes in zip(*muestras[:-1]))
    matriz = ajustar_proyeccion(xyz, uv)
    informe = {"proyeccion_depth_a_rgb": matriz.tolist(), "poses": []}
    for pose, (puntos, observados) in zip(poses, muestras):
        calculados = proyectar(matriz, puntos)
        error = np.linalg.norm(calculados - observados, axis=1)
        # Referencia en la misma foto al superponer los píxeles sin proyección.
        error_crudo = np.linalg.norm(np.asarray(pose["esquinas_depth"]) - observados, axis=1)
        informe["poses"].append({
            "captura": pose["carpeta"],
            "validacion": pose.get("validacion", False),
            "error_px": error.tolist(),
            "rmse_px": float(np.sqrt(np.mean(error**2))),
            "maximo_px": float(error.max()),
            "rmse_crudo_px": float(np.sqrt(np.mean(error_crudo**2))),
            "esquinas_proyectadas_rgb": calculados.tolist(),
        })
    with args.salida.open("x", encoding="utf-8") as archivo:
        json.dump(informe, archivo, indent=2, allow_nan=False)
    print(json.dumps(informe["poses"], indent=2))


if __name__ == "__main__":
    main()
