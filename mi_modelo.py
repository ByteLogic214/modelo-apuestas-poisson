import os
import requests
import math
import csv
from datetime import datetime

# 1. Configuración de Credenciales
API_KEY = os.getenv("API_FOOTBALL_KEY")
HEADERS = {"X-Auth-Token": API_KEY}

def obtener_datos_liga(id_liga):
    url = f"https://football-data.org{id_liga}/matches?status=FINISHED"
    respuesta = requests.get(url, headers=HEADERS)
    if respuesta.status_code != 200:
        return None
    return respuesta.json().get("matches", [])

def obtener_partidos_hoy(id_liga):
    url = f"https://football-data.org{id_liga}/matches?status=SCHEDULED"
    respuesta = requests.get(url, headers=HEADERS)
    if respuesta.status_code != 200:
        return []
    return respuesta.json().get("matches", [])

def calcular_poisson(k, lam):
    if lam <= 0:
        return 0
    return (math.pow(lam, k) * math.exp(-lam)) / math.factorial(k)

def procesar_modelo():
    id_liga = "PL"
    partidos_jugados = obtener_datos_liga(id_liga)
    partidos_hoy = obtener_partidos_hoy(id_liga)
    
    if not partidos_jugados or not partidos_hoy:
        print("No hay datos suficientes o no hay partidos para hoy.")
        return

    total_goles_local = 0
    total_goles_visitante = 0
    total_partidos = len(partidos_jugados)
    equipos = {}

    for partido in partidos_jugados:
        local = partido["homeTeam"]["name"]
        visitante = partido["awayTeam"]["name"]
        goles_l = partido["score"]["fullTime"]["home"]
        goles_v = partido["score"]["fullTime"]["away"]
        
        if goles_l is None or goles_v is None:
            continue
            
        total_goles_local += goles_l
        total_goles_visitante += goles_v
        
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

    pgl = total_goles_local / total_partidos
    pgv = total_goles_visitante / total_partidos

    # Preparar el archivo CSV para guardar resultados
    nombre_archivo = "predicciones_historico.csv"
    existe_archivo = os.path.exists(nombre_archivo)
    
    # Abrir el archivo en modo "append" (añadir filas al final)
    with open(nombre_archivo, mode="a", newline="", encoding="utf-8") as archivo_csv:
        campos = ["Fecha_Calculo", "Liga", "Local", "Visitante", "Goles_Exp_Local", "Goles_Exp_Vis", "Prob_1", "Prob_X", "Prob_2", "Cuota_1", "Cuota_X", "Cuota_2"]
        escritor = csv.DictWriter(archivo_csv, fieldnames=campos, delimiter=";")
        
        if not existe_archivo:
            escritor.writeheader() # Escribe los títulos de columna si el archivo es nuevo
            
        fecha_actual = datetime.now().strftime("%Y-%m-%d")

        for partido in partidos_hoy:
            eq_local = partido["homeTeam"]["name"]
            eq_visitante = partido["awayTeam"]["name"]
            
            if eq_local not in equipos or eq_visitante not in equipos:
                continue
                
            fac = (equipos[eq_local]["goles_anotados_casa"] / equipos[eq_local]["partidos_casa"]) / pgl
            fdv = (equipos[eq_visitante]["goles_recibidos_fuera"] / equipos[eq_visitante]["partidos_fuera"]) / pgl
            fav = (equipos[eq_visitante]["goles_anotados_fuera"] / equipos[eq_visitante]["partidos_fuera"]) / pgv
            fdl = (equipos[eq_local]["goles_recibidos_casa"] / equipos[eq_local]["partidos_casa"]) / pgv
            
            lambda_local = fac * fdv * pgl
            lambda_visitante = fav * fdl * pgv
            
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
                        
            cuota_local = 1 / prob_local if prob_local > 0 else 999
            cuota_empate = 1 / prob_empate if prob_empate > 0 else 999
            cuota_visitante = 1 / prob_visitante if prob_visitante > 0 else 999
            
            # Guardar fila de datos
            escritor.writerow({
                "Fecha_Calculo": fecha_actual,
                "Liga": id_liga,
                "Local": eq_local,
                "Visitante": eq_visitante,
                "Goles_Exp_Local": round(lambda_local, 2),
                "Goles_Exp_Vis": round(lambda_visitante, 2),
                "Prob_1": f"{round(prob_local * 100, 1)}%",
                "Prob_X": f"{round(prob_empate * 100, 1)}%",
                "Prob_2": f"{round(prob_visitante * 100, 1)}%",
                "Cuota_1": round(cuota_local, 2),
                "Cuota_X": round(cuota_empate, 2),
                "Cuota_2": round(cuota_visitante, 2)
            })
            print(f"Predicción guardada para: {eq_local} vs {eq_visitante}")

if __name__ == "__main__":
    procesar_modelo()
