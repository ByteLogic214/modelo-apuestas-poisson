import os
import requests
import math

# 1. Configuración de Credenciales con tu Secreto Corregido
API_KEY = os.getenv("API_FOOTBALL_KEY")
HEADERS = {"X-Auth-Token": API_KEY}

def obtener_datos_liga(id_liga):
    """Descarga los partidos jugados para calcular las medias de la liga."""
    url = f"https://football-data.org{id_liga}/matches?status=FINISHED"
    respuesta = requests.get(url, headers=HEADERS)
    if respuesta.status_code != 200:
        print(f"Error al obtener datos de la liga {id_liga}: {respuesta.status_code}")
        return None
    return respuesta.json().get("matches", [])

def obtener_partidos_hoy(id_liga):
    """Descarga los partidos programados para el día de hoy."""
    url = f"https://football-data.org{id_liga}/matches?status=SCHEDULED"
    respuesta = requests.get(url, headers=HEADERS)
    if respuesta.status_code != 200:
        return []
    return respuesta.json().get("matches", [])

def calcular_poisson(k, lam):
    """Calcula la probabilidad exacta de Poisson para 'k' eventos con una media 'lam'."""
    if lam <= 0:
        return 0
    return (math.pow(lam, k) * math.exp(-lam)) / math.factorial(k)

def procesar_modelo():
    # Usamos la Premier League de Inglaterra (ID: PL) como ejemplo base
    id_liga = "PL"
    partidos_jugados = obtener_datos_liga(id_liga)
    partidos_hoy = obtener_partidos_hoy(id_liga)
    
    if not partidos_jugados:
        print("No se pudieron procesar las estadísticas de la liga.")
        return
        
    if not partidos_hoy:
        print("No hay partidos programados para hoy en esta competición.")
        return

    # 2. Inicializar métricas globales
    total_goles_local = 0
    total_goles_visitante = 0
    total_partidos = len(partidos_jugados)
    
    # Diccionarios para estadísticas por equipo
    equipos = {}

    # 3. Analizar el histórico de la temporada
    for partido in partidos_jugados:
        local = partido["homeTeam"]["name"]
        visitante = partido["awayTeam"]["name"]
        goles_l = partido["score"]["fullTime"]["home"]
        goles_v = partido["score"]["fullTime"]["away"]
        
        # Omitir si faltan datos en el registro
        if goles_l is None or goles_v is None:
            continue
            
        total_goles_local += goles_l
        total_goles_visitante += goles_v
        
        # Asegurar que los equipos existan en el diccionario
        for eq in [local, visitante]:
            if eq not in equipos:
                equipos[eq] = {"goles_anotados_casa": 0, "goles_recibidos_casa": 0, "partidos_casa": 0,
                               "goles_anotados_fuera": 0, "goles_recibidos_fuera": 0, "partidos_fuera": 0}
                               
        equipos[local]["goles_anotados_casa"] += goles_l
        equipos[local]["goles_recibidos_casa"] += goles_v
        equipos[local]["partidos_casa"] += 1
        
        equipos[visitante]["goles_anotados_fuera"] += goles_v
        equipos[visitante]["goles_recibidos_fuera"] += goles_l
        equipos[visitante]["partidos_fuera"] += 1

    # Promedios generales de la liga
    pgl = total_goles_local / total_partidos
    pgv = total_goles_visitante / total_partidos

    print(f"--- PREDICCIONES PARA HOY ({id_liga}) ---")
    print(f"Promedio Goles Local Liga: {pgl:.2f} | Promedio Goles Visitante Liga: {pgv:.2f}\n")

    # 4. Calcular probabilidades de los partidos de hoy
    for partido in partidos_hoy:
        eq_local = partido["homeTeam"]["name"]
        eq_visitante = partido["awayTeam"]["name"]
        
        # Validación por si un equipo no tiene partidos registrados aún
        if eq_local not in equipos or eq_visitante not in equipos:
            continue
            
        # Fuerza de ataque y defensa
        fac = (equipos[eq_local]["goles_anotados_casa"] / equipos[eq_local]["partidos_casa"]) / pgl
        fdv = (equipos[eq_visitante]["goles_recibidos_fuera"] / equipos[eq_visitante]["partidos_fuera"]) / pgl
        fav = (equipos[eq_visitante]["goles_anotados_fuera"] / equipos[eq_visitante]["partidos_fuera"]) / pgv
        fdl = (equipos[eq_local]["goles_recibidos_casa"] / equipos[eq_local]["partidos_casa"]) / pgv
        
        # Goles esperados (Lambda)
        lambda_local = fac * fdv * pgl
        lambda_visitante = fav * fdl * pgv
        
        # Calcular matriz de probabilidades (hasta 5 goles por equipo)
        prob_local = 0.0
        prob_empate = 0.0
        prob_visitante = 0.0
        
        for x in range(6):
            for y in range(6):
                p_x = calcular_poisson(x, lambda_local)
                p_y = calcular_poisson(y, lambda_visitante)
                p_marcador = p_x * p_y
                
                if x > y:
                    prob_local += p_marcador
                elif x == y:
                    prob_empate += p_marcador
                else:
                    prob_visitante += p_marcador
                    
        # Calcular Cuotas Justas Teóricas del Modelo
        cuota_local = 1 / prob_local if prob_local > 0 else 999
        cuota_empate = 1 / prob_empate if prob_empate > 0 else 999
        cuota_visitante = 1 / prob_visitante if prob_visitante > 0 else 999
        
        print(f"Partido: {eq_local} vs {eq_visitante}")
        print(f"  Goles Esperados -> Local: {lambda_local:.2f} | Visitante: {lambda_visitante:.2f}")
        print(f"  Probabilidades  -> Local: {prob_local*100:.1f}% | Empate: {prob_empate*100:.1f}% | Visitante: {prob_visitante*100:.1f}%")
        print(f"  Cuotas Justas   -> Local: {cuota_local:.2f} | Empate: {cuota_empate:.2f} | Visitante: {cuota_visitante:.2f}")
        print("-" * 50)

if __name__ == "__main__":
    procesar_modelo()
