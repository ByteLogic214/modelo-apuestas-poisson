import os
import requests
from requests.exceptions import RequestException
import math
import csv
import time
from datetime import datetime

# ============================================================
# CONFIGURACIÓN
# ============================================================
API_KEY = os.getenv("API_FOOTBALL_KEY")
HEADERS = {"X-Auth-Token": API_KEY}
LIGA = "PL"  # Premier League
MAX_RETRIES = 3
RETRY_DELAY = 5  # segundos entre reintentos

# ============================================================
# FUNCIONES AUXILIARES CON REINTENTOS Y MANEJO DE ERRORES
# ============================================================
def fetch_data(url, max_retries=MAX_RETRIES, delay=RETRY_DELAY):
    """Realiza una petición GET con reintentos y retardo por rate limiting."""
    for intento in range(1, max_retries + 1):
        try:
            respuesta = requests.get(url, headers=HEADERS, timeout=15)
            # Si el código es 200, devolvemos el JSON
            if respuesta.status_code == 200:
                return respuesta.json()
            # Si hay rate limiting (429) o error de servidor (5xx), reintentamos
            elif respuesta.status_code in (429, 500, 502, 503, 504):
                print(f"Intento {intento}/{max_retries} - Código {respuesta.status_code}. Esperando {delay}s...")
                time.sleep(delay)
            else:
                # Error no recuperable (401, 403, 404, etc.)
                print(f"Error fatal en API: Código {respuesta.status_code}")
                return None
        except RequestException as e:
            print(f"Error de red en intento {intento}/{max_retries}: {e}")
            if intento < max_retries:
                time.sleep(delay)
            else:
                print("Se agotaron los reintentos. Abortando.")
                return None
    return None

def obtener_datos_liga(id_liga):
    """Obtiene partidos finalizados de la liga (histórico)."""
    url = f"https://api.football-data.org/v4/competitions/{id_liga}/matches?status=FINISHED"
    try:
        data = fetch_data(url)
        if data and "matches" in data:
            return data["matches"]
        else:
            print(f"No se encontraron partidos para la liga {id_liga}")
            return []
    except Exception as e:
        print(f"Error inesperado en obtener_datos_liga: {e}")
        return []

def obtener_partidos_hoy(id_liga):
    """Obtiene partidos programados para hoy en la liga."""
    url = f"https://api.football-data.org/v4/competitions/{id_liga}/matches?status=SCHEDULED"
    try:
        data = fetch_data(url)
        if data and "matches" in data:
            return data["matches"]
        else:
            return []
    except Exception as e:
        print(f"Error inesperado en obtener_partidos_hoy: {e}")
        return []

# ============================================================
# MODELO DE POISSON MEJORADO
# ============================================================
def calcular_poisson(k, lam):
    """Función de probabilidad de Poisson."""
    if lam <= 0:
        return 0.0
    return (math.pow(lam, k) * math.exp(-lam)) / math.factorial(k)

def calcular_probabilidades_marcador(lambda_local, lambda_vis, max_goles=5):
    """
    Calcula matriz de probabilidades de marcadores (hasta max_goles goles por equipo)
    y devuelve: prob_local, prob_empate, prob_visitante, prob_over_2_5.
    """
    prob_local = 0.0
    prob_empate = 0.0
    prob_visitante = 0.0
    prob_over_2_5 = 0.0

    for x in range(max_goles + 1):
        for y in range(max_goles + 1):
            p_x = calcular_poisson(x, lambda_local)
            p_y = calcular_poisson(y, lambda_vis)
            p_marcador = p_x * p_y

            if x > y:
                prob_local += p_marcador
            elif x == y:
                prob_empate += p_marcador
            else:
                prob_visitante += p_marcador

            # Goles totales > 2.5 (al menos 3 goles)
            if x + y >= 3:
                prob_over_2_5 += p_marcador

    # Normalizar para que la suma sea exactamente 1 (redondeo numérico)
    suma = prob_local + prob_empate + prob_visitante
    if suma > 0:
        factor = 1.0 / suma
        prob_local *= factor
        prob_empate *= factor
        prob_visitante *= factor

    return prob_local, prob_empate, prob_visitante, prob_over_2_5

def calcular_margen_valor(prob_local, prob_empate, prob_visitante):
    """
    Calcula un indicador de valor: diferencia porcentual entre la probabilidad más alta
    y la probabilidad justa (1/3). Si el margen supera el 20%, etiqueta como 'Alto'.
    """
    max_prob = max(prob_local, prob_empate, prob_visitante)
    baseline = 1.0 / 3.0
    if max_prob == 0:
        return "N/A"
    margen = ((max_prob - baseline) / baseline) * 100
    if margen > 20:
        return "Alto"
    else:
        return "Normal"

# ============================================================
# PROCESO PRINCIPAL
# ============================================================
def procesar_modelo():
    id_liga = LIGA
    print("Obteniendo datos históricos de la liga...")
    partidos_jugados = obtener_datos_liga(id_liga)
    if not partidos_jugados:
        print("No se pudieron obtener partidos históricos. Saliendo.")
        return

    print("Obteniendo partidos programados para hoy...")
    partidos_hoy = obtener_partidos_hoy(id_liga)
    if not partidos_hoy:
        print("No hay partidos programados para hoy. Saliendo.")
        return

    # Variables para promedios de la liga
    total_goles_local = 0
    total_goles_visitante = 0
    total_partidos = 0
    equipos = {}

    # Procesar partidos jugados para estadísticas
    for partido in partidos_jugados:
        try:
            local = partido["homeTeam"]["name"]
            visitante = partido["awayTeam"]["name"]
            goles_l = partido["score"]["fullTime"]["home"]
            goles_v = partido["score"]["fullTime"]["away"]

            if goles_l is None or goles_v is None:
                continue

            total_goles_local += goles_l
            total_goles_visitante += goles_v
            total_partidos += 1

            # Inicializar equipos si no existen
            for eq in [local, visitante]:
                if eq not in equipos:
                    equipos[eq] = {
                        "goles_anotados_casa": 0,
                        "goles_recibidos_casa": 0,
                        "partidos_casa": 0,
                        "goles_anotados_fuera": 0,
                        "goles_recibidos_fuera": 0,
                        "partidos_fuera": 0
                    }

            equipos[local]["goles_anotados_casa"] += goles_l
            equipos[local]["goles_recibidos_casa"] += goles_v
            equipos[local]["partidos_casa"] += 1
            equipos[visitante]["goles_anotados_fuera"] += goles_v
            equipos[visitante]["goles_recibidos_fuera"] += goles_l
            equipos[visitante]["partidos_fuera"] += 1
        except KeyError as e:
            print(f"Advertencia: Error al procesar partido histórico: {e}")
            continue

    if total_partidos == 0:
        print("No se pudieron calcular estadísticas (sin partidos válidos).")
        return

    pgl = total_goles_local / total_partidos
    pgv = total_goles_visitante / total_partidos

    # Archivo CSV
    nombre_archivo = "predicciones_historico.csv"
    existe_archivo = os.path.exists(nombre_archivo)

    # Cabeceras con las nuevas columnas
    campos = [
        "Fecha_Calculo", "Liga", "Local", "Visitante",
        "Goles_Exp_Local", "Goles_Exp_Vis",
        "Prob_1", "Prob_X", "Prob_2",
        "Cuota_1", "Cuota_X", "Cuota_2",
        "Over_2_5_Prob", "Margen_Valor"
    ]

    with open(nombre_archivo, mode="a", newline="", encoding="utf-8-sig") as archivo_csv:
        escritor = csv.DictWriter(archivo_csv, fieldnames=campos, delimiter=";")

        if not existe_archivo:
            escritor.writeheader()

        fecha_actual = datetime.now().strftime("%Y-%m-%d")

        for partido in partidos_hoy:
            try:
                eq_local = partido["homeTeam"]["name"]
                eq_visitante = partido["awayTeam"]["name"]
            except KeyError:
                print("Advertencia: partido sin nombres de equipo, saltando.")
                continue

            if eq_local not in equipos or eq_visitante not in equipos:
                print(f"Equipo(s) sin datos históricos: {eq_local} vs {eq_visitante}, omitiendo.")
                continue

            # Calcular factores de ataque/defensa
            try:
                fac = (equipos[eq_local]["goles_anotados_casa"] / equipos[eq_local]["partidos_casa"]) / pgl if pgl > 0 else 0
                fdv = (equipos[eq_visitante]["goles_recibidos_fuera"] / equipos[eq_visitante]["partidos_fuera"]) / pgl if pgl > 0 else 0
                fav = (equipos[eq_visitante]["goles_anotados_fuera"] / equipos[eq_visitante]["partidos_fuera"]) / pgv if pgv > 0 else 0
                fdl = (equipos[eq_local]["goles_recibidos_casa"] / equipos[eq_local]["partidos_casa"]) / pgv if pgv > 0 else 0
            except ZeroDivisionError:
                print(f"Advertencia: División por cero para {eq_local} vs {eq_visitante}, omitiendo.")
                continue

            lambda_local = fac * fdv * pgl
            lambda_visitante = fav * fdl * pgv

            # Calcular probabilidades y Over 2.5
            prob_local, prob_empate, prob_visitante, prob_over_2_5 = \
                calcular_probabilidades_marcador(lambda_local, lambda_visitante)

            cuota_local = 1 / prob_local if prob_local > 0 else 999
            cuota_empate = 1 / prob_empate if prob_empate > 0 else 999
            cuota_visitante = 1 / prob_visitante if prob_visitante > 0 else 999

            margen_valor = calcular_margen_valor(prob_local, prob_empate, prob_visitante)

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
                "Cuota_2": round(cuota_visitante, 2),
                "Over_2_5_Prob": f"{round(prob_over_2_5 * 100, 1)}%",
                "Margen_Valor": margen_valor
            })
            print(f"✅ Predicción guardada: {eq_local} vs {eq_visitante}")

if __name__ == "__main__":
    procesar_modelo()
