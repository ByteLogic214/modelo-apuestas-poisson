import os
import requests
from requests.exceptions import RequestException
import math
import csv
import time
from datetime import datetime

# ============================================================
# CONFIGURACIÓN GLOBAL
# ============================================================
API_KEY = os.getenv("API_FOOTBALL_KEY")
if not API_KEY:
    raise ValueError("❌ ERROR: La variable de entorno 'API_FOOTBALL_KEY' no está definida. "
                     "Asegúrate de configurar el secreto en GitHub → Settings → Secrets → Actions.")

HEADERS = {"X-Auth-Token": API_KEY}
MAX_RETRIES = 3
RETRY_DELAY = 5           # segundos entre reintentos
LIGUE_DELAY = 3           # delay entre peticiones de distintas ligas
MARGEN_CASA = 0.05        # margen simulado de la casa (5%)
KELLY_FRACCION = 0.25     # fracción de Kelly (25%)
UMBRAL_EV = 0.05          # valor esperado mínimo (5%)

# Ligas a procesar
LIGAS = ["PL", "PD", "SA", "BL1", "CL"]   # Premier, LaLiga, Serie A, Bundesliga, Champions

# ============================================================
# FUNCIONES AUXILIARES DE RED (con reintentos y manejo de 400)
# ============================================================
def fetch_data(url, max_retries=MAX_RETRIES, delay=RETRY_DELAY):
    """
    Realiza una petición GET con reintentos.
    - Error 400 = clave inválida o petición mal formada → NO reintenta, mensaje claro.
    - Error 429/5xx → reintenta con espera.
    """
    for intento in range(1, max_retries + 1):
        try:
            respuesta = requests.get(url, headers=HEADERS, timeout=15)
            if respuesta.status_code == 200:
                return respuesta.json()
            elif respuesta.status_code == 400:
                print("🚨 Error 400: La solicitud es inválida. Probablemente la clave API no es correcta "
                      "o no está configurada en el entorno. Verifica el secreto en GitHub.")
                return None
            elif respuesta.status_code == 401:
                print("🚨 Error 401: No autorizado. Revisa la clave API.")
                return None
            elif respuesta.status_code == 403:
                print("🚨 Error 403: Acceso denegado. Posiblemente el plan gratuito no permite esta liga.")
                return None
            elif respuesta.status_code in (429, 500, 502, 503, 504):
                print(f"⚠️ Intento {intento}/{max_retries} - Código {respuesta.status_code}. Esperando {delay}s...")
                time.sleep(delay)
            else:
                print(f"❌ Error fatal en API: Código {respuesta.status_code}")
                return None
        except RequestException as e:
            print(f"🔴 Error de red en intento {intento}/{max_retries}: {e}")
            if intento < max_retries:
                time.sleep(delay)
            else:
                print("Se agotaron los reintentos. Abortando.")
                return None
    return None

def obtener_datos_liga(id_liga):
    url = f"https://api.football-data.org/v4/competitions/{id_liga}/matches?status=FINISHED"
    try:
        data = fetch_data(url)
        if data and "matches" in data:
            return data["matches"]
        else:
            print(f"📭 No se encontraron partidos para la liga {id_liga}")
            return []
    except Exception as e:
        print(f"Error inesperado en obtener_datos_liga: {e}")
        return []

def obtener_partidos_hoy(id_liga):
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
# MODELO DE POISSON
# ============================================================
def calcular_poisson(k, lam):
    if lam <= 0:
        return 0.0
    return (math.pow(lam, k) * math.exp(-lam)) / math.factorial(k)

def calcular_probabilidades_marcador(lambda_local, lambda_vis, max_goles=5):
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

            if x + y >= 3:
                prob_over_2_5 += p_marcador

    suma = prob_local + prob_empate + prob_visitante
    if suma > 0:
        factor = 1.0 / suma
        prob_local *= factor
        prob_empate *= factor
        prob_visitante *= factor

    return prob_local, prob_empate, prob_visitante, prob_over_2_5

# ============================================================
# VALUE BETTING & KELLY
# ============================================================
def simular_cuota_mercado(prob_modelo):
    if prob_modelo <= 0:
        return 999
    prob_con_margen = prob_modelo * (1 + MARGEN_CASA)
    return 1.0 / prob_con_margen if prob_con_margen > 0 else 999

def calcular_valor_esperado(cuota_mercado, prob_modelo):
    return (cuota_mercado * prob_modelo) - 1.0

def calcular_stake_kelly(cuota_mercado, prob_modelo, fraccion=KELLY_FRACCION):
    if cuota_mercado <= 1:
        return 0.0
    f = (cuota_mercado * prob_modelo - 1) / (cuota_mercado - 1)
    if f <= 0:
        return 0.0
    stake = min(f * fraccion, 0.25)
    return round(stake, 4)

# ============================================================
# PROCESO POR LIGA
# ============================================================
def procesar_liga(id_liga):
    print(f"\n{'='*60}")
    print(f"Procesando liga: {id_liga}")
    print(f"{'='*60}")

    partidos_jugados = obtener_datos_liga(id_liga)
    if not partidos_jugados:
        print(f"Saltando {id_liga} (sin datos históricos).")
        return []

    partidos_hoy = obtener_partidos_hoy(id_liga)
    if not partidos_hoy:
        print(f"No hay partidos programados hoy para {id_liga}. Saltando.")
        return []

    # Estadísticas de la liga
    total_goles_local = 0
    total_goles_visitante = 0
    total_partidos = 0
    equipos = {}

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
        except KeyError:
            continue

    if total_partidos == 0:
        print(f"No hay partidos históricos válidos para {id_liga}.")
        return []

    pgl = total_goles_local / total_partidos
    pgv = total_goles_visitante / total_partidos

    predicciones = []

    for partido in partidos_hoy:
        try:
            eq_local = partido["homeTeam"]["name"]
            eq_visitante = partido["awayTeam"]["name"]
        except KeyError:
            continue

        if eq_local not in equipos or eq_visitante not in equipos:
            print(f"Sin datos para {eq_local} vs {eq_visitante} en {id_liga}. Omitiendo.")
            continue

        try:
            fac = (equipos[eq_local]["goles_anotados_casa"] / equipos[eq_local]["partidos_casa"]) / pgl if pgl > 0 else 0
            fdv = (equipos[eq_visitante]["goles_recibidos_fuera"] / equipos[eq_visitante]["partidos_fuera"]) / pgl if pgl > 0 else 0
            fav = (equipos[eq_visitante]["goles_anotados_fuera"] / equipos[eq_visitante]["partidos_fuera"]) / pgv if pgv > 0 else 0
            fdl = (equipos[eq_local]["goles_recibidos_casa"] / equipos[eq_local]["partidos_casa"]) / pgv if pgv > 0 else 0
        except ZeroDivisionError:
            continue

        lambda_local = fac * fdv * pgl
        lambda_visitante = fav * fdl * pgv

        prob_local, prob_empate, prob_visitante, prob_over_2_5 = \
            calcular_probabilidades_marcador(lambda_local, lambda_visitante)

        # Evaluar cada mercado
        resultados = [
            ("1", eq_local, prob_local),
            ("X", "Empate", prob_empate),
            ("2", eq_visitante, prob_visitante),
            ("Over 2.5", f"{eq_local} vs {eq_visitante}", prob_over_2_5)
        ]

        for mercado, descripcion, prob_modelo in resultados:
            if prob_modelo <= 0:
                continue

            cuota_justa = 1 / prob_modelo if prob_modelo > 0 else 999
            cuota_mercado = simular_cuota_mercado(prob_modelo)
            ev = calcular_valor_esperado(cuota_mercado, prob_modelo)

            if ev > UMBRAL_EV:
                stake = calcular_stake_kelly(cuota_mercado, prob_modelo)
                prediccion = {
                    "Fecha_Calculo": datetime.now().strftime("%Y-%m-%d"),
                    "Liga": id_liga,
                    "Partido": f"{eq_local} vs {eq_visitante}",
                    "Mercado": mercado,
                    "Pronostico_Sugerido": descripcion if mercado in ["1","X","2"] else "Over 2.5",
                    "Cuota_Recomendada": round(cuota_mercado, 2),
                    "Stake_Asignado_Pct": round(stake * 100, 2),
                    "Probabilidad_Modelo_Pct": round(prob_modelo * 100, 1),
                    "Valor_Esperado": round(ev * 100, 2),
                    "Resultado_Final": ""
                }
                predicciones.append(prediccion)
                print(f"✅ Apuesta: {mercado} {descripcion} | Cuota {cuota_mercado} | Stake {stake*100:.2f}% | EV {ev*100:.2f}%")
            else:
                print(f"ℹ️ Sin valor en {mercado} para {eq_local} vs {eq_visitante} (EV: {ev*100:.2f}%)")

    return predicciones

def main():
    todas_predicciones = []

    for liga in LIGAS:
        preds = procesar_liga(liga)
        todas_predicciones.extend(preds)
        if liga != LIGAS[-1]:
            print(f"Esperando {LIGUE_DELAY} segundos antes de la siguiente liga...")
            time.sleep(LIGUE_DELAY)

    # Guardar CSV
    nombre_archivo = "predicciones_historico.csv"
    existe_archivo = os.path.exists(nombre_archivo)

    campos = [
        "Fecha_Calculo", "Liga", "Partido", "Mercado",
        "Pronostico_Sugerido", "Cuota_Recomendada", "Stake_Asignado_Pct",
        "Probabilidad_Modelo_Pct", "Valor_Esperado", "Resultado_Final"
    ]

    with open(nombre_archivo, mode="a", newline="", encoding="utf-8-sig") as archivo_csv:
        escritor = csv.DictWriter(archivo_csv, fieldnames=campos, delimiter=";")
        if not existe_archivo:
            escritor.writeheader()
        for pred in todas_predicciones:
            escritor.writerow(pred)

    print(f"\n✅ Proceso completado. {len(todas_predicciones)} apuestas registradas en '{nombre_archivo}'.")

if __name__ == "__main__":
    main()
