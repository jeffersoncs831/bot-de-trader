import websocket
import json
import pandas as pd
import numpy as np
import time

# === CONFIGURAÇÕES DO ROBÔ ===
TOKEN = "VjNovR9q9lnDX3q"
STAKE = 1.0
META_LUCRO = 15.0
STOP_LOSS = 5.0
SIMBOLO = "R_100"

# === VARIÁVEIS GLOBAIS ===
lucro_total = 0
precos = []
ws = None
ordem_em_andamento = False
ultimo_contract_id = None
tipo_ordem_atual = ""
ultimo_trade_time = 0
cooldown = 5  # segundos

# === INDICADORES ===
def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calculate_rsi(series, period=14):
    delta = series.diff()
    ganho = delta.where(delta > 0, 0).rolling(window=period).mean()
    perda = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = ganho / perda
    return 100 - (100 / (1 + rs))

# === LÓGICA DE ENTRADA COM EMA + RSI ===
def decide_trade_ema_rsi(series):
    ema_curta = calculate_ema(series, 5)
    ema_longa = calculate_ema(series, 20)
    rsi = calculate_rsi(series, 14)

    cruzou_para_cima = ema_curta.iloc[-2] < ema_longa.iloc[-2] and ema_curta.iloc[-1] > ema_longa.iloc[-1]
    cruzou_para_baixo = ema_curta.iloc[-2] > ema_longa.iloc[-2] and ema_curta.iloc[-1] < ema_longa.iloc[-1]

    rsi_atual = rsi.iloc[-1]

    if cruzou_para_cima and rsi_atual < 70:
        return "CALL"
    elif cruzou_para_baixo and rsi_atual > 30:
        return "PUT"
    return "SEM ENTRADA"

# === SALVAR RESULTADO EM RELATÓRIO ===
def salvar_resultado(ativo, tipo, resultado, lucro):
    with open("relatorio_operacoes.txt", "a") as f:
        horario = time.strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"{horario},{ativo},{tipo},{resultado},R${lucro:.2f}\n")

# === ENVIAR ORDEM ===
def enviar_ordem_real(tipo_ordem):
    global ordem_em_andamento, tipo_ordem_atual, ultimo_trade_time
    tipo_ordem_atual = tipo_ordem
    ordem_em_andamento = True
    ultimo_trade_time = time.time()
    print(f"\n📤 Enviando ORDEM REAL: {tipo_ordem} | Valor: R${STAKE:.2f}")
    contrato = {
        "buy": 1,
        "price": STAKE,
        "parameters": {
            "amount": STAKE,
            "basis": "stake",
            "contract_type": tipo_ordem,
            "currency": "USD",
            "duration": 1,
            "duration_unit": "t",
            "symbol": SIMBOLO
        }
    }
    ws.send(json.dumps(contrato))

# === CONSULTAR CONTRATO PELO ID ===
def consultar_contrato(contract_id):
    consulta = {
        "proposal_open_contract": 1,
        "contract_id": contract_id
    }
    ws.send(json.dumps(consulta))

# === AO RECEBER MENSAGEM ===
def on_message(wsapp, message):
    global precos, lucro_total, ordem_em_andamento, ultimo_contract_id, ultimo_trade_time

    data = json.loads(message)

    if lucro_total >= META_LUCRO:
        print("\n🏁 META DE LUCRO ALCANÇADA! Encerrando robô.")
        wsapp.close()
        return

    if lucro_total <= -abs(STOP_LOSS):
        print("\n🛑 STOP LOSS atingido! Encerrando robô.")
        wsapp.close()
        return

    if data.get("msg_type") == "authorize":
        print("✅ Autenticado com sucesso. Coletando dados...")
        wsapp.send(json.dumps({"ticks": SIMBOLO}))
        return

    if data.get("msg_type") == "buy":
        ultimo_contract_id = data["buy"]["contract_id"]
        print("📨 Contrato enviado. Aguardando resultado...")
        time.sleep(2)
        consultar_contrato(ultimo_contract_id)
        return

    if data.get("msg_type") == "proposal_open_contract":
        contrato = data["proposal_open_contract"]
        if contrato["is_sold"]:
            lucro = contrato["profit"]
            resultado = "WIN" if lucro > 0 else "LOSS"
            lucro_total += lucro
            print(f"🏁 Resultado: {resultado} | Lucro: R${lucro:.2f} | Total: R${lucro_total:.2f}")
            salvar_resultado(SIMBOLO, tipo_ordem_atual, resultado, lucro)
            ordem_em_andamento = False
        else:
            time.sleep(1)
            consultar_contrato(ultimo_contract_id)
        return

    if "tick" in data and not ordem_em_andamento:
        preco = float(data["tick"]["quote"])
        precos.append(preco)

        if len(precos) >= 50:
            precos = precos[-50:]
            serie = pd.Series(precos)
            decisao = decide_trade_ema_rsi(serie)
            print(f"📊 Preço: {preco:.2f} → {decisao}")
            if decisao in ["CALL", "PUT"] and time.time() - ultimo_trade_time >= cooldown:
                enviar_ordem_real(decisao)
        else:
            print(f"⏳ Coletando dados... ({len(precos)}/50)")

# === INÍCIO DA CONEXÃO ===
def on_open(wsapp):
    wsapp.send(json.dumps({"authorize": TOKEN}))

# === INICIAR ROBÔ ===
def start_deriv_bot():
    global ws
    ws = websocket.WebSocketApp(
        "wss://ws.binaryws.com/websockets/v3?app_id=1089",
        on_open=on_open,
        on_message=on_message
    )
    ws.run_forever()

start_deriv_bot()
