"""Геометрические утилиты — pure-Python, без внешних зависимостей.

point_in_polygon использует алгоритм трассировки луча (ray-casting).
Полигон задаётся как список пар [lat, lng] (конвенция Leaflet).
"""


def point_in_polygon(lat: float, lon: float, polygon: list[list[float]]) -> bool:
    """Возвращает True, если точка (lat, lon) находится внутри полигона.

    Полигон: список точек [[lat0, lng0], [lat1, lng1], ...].
    Ребро между последней и первой точкой замыкается автоматически.
    Менее 3 вершин → всегда False.
    """
    n = len(polygon)
    if n < 3:
        return False

    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i][1], polygon[i][0]  # lon, lat
        xj, yj = polygon[j][1], polygon[j][0]
        # Ray crossing test (horizontal ray to the right)
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i

    return inside
