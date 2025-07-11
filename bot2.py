import websocket
import json
import pandas as pd
import numpy as np
import time
from flask import Flask, jsonify
import threading

# === CONFIGURAÇÕES DO ROBÔ ===
TOKEN = "VjNovR9q9lnDX3q"
STAKE_INICIAL = 100.0
META_LUCRO = 500.0
STOP_LOSS = 300.0
SIMBOLO = "R_100"

# === VARIÁVEIS GLOBAIS ===
lucro_total = 0
precos = []
ws = None
ordem_em_andamento = False
ultimo_contract_id = None
tipo_ordem_atual = ""
stake_atual = STAKE_INICIAL
ultima_ordem_timestamp = 0
ultima_operacao = ""

# === FLASK APP PARA MONITORAMENTO ===
app = Flask(__name__)

@app.route("/status")
def status():
    return jsonify({
        "lucro_total": round(lucro_total, 2),
        "stake_atual": stake_atual,
        "ultima_operacao": ultima_operacao,
        "ordem_em_andamento": ordem_em_andamento
    })

def run_flask():
    app.run(port=5001)

threading.Thread(target=run_flask, daemon=True).start()

# === INDICADORES ===
def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calculate_rsi(series, period=14):
    delta = series.diff()
    ganho = delta.where(delta > 0, 0).rolling(window=period).mean()
    perda = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = ganho / perda
    return 100 - (100 / (1 + rs))

def is_lateralizado(series, limite=0.05):
    return series[-20:].std() < limite

# === DECISÃO DE ENTRADA ===
def decide_trade(preco, ema, rsi, serie):
    if is_lateralizado(serie):
        return "SEM ENTRADA"
    if preco > ema and rsi < 80:
        return "CALL"
    elif preco < ema and rsi > 20:
        return "PUT"
    return "SEM ENTRADA"

# === SALVAR RESULTADO ===
def salvar_resultado(ativo, tipo, resultado, lucro):
    global ultima_operacao
    horario = time.strftime("%Y-%m-%d %H:%M:%S")
    ultima_operacao = f"{horario},{ativo},{tipo},{resultado},R${lucro:.2f}"
    with open("relatorio_operacoes.txt", "a") as f:
        f.write(ultima_operacao + "\n")

# === ENVIAR ORDEM ===
def enviar_ordem_real(tipo_ordem):
    global ordem_em_andamento, tipo_ordem_atual, ultima_ordem_timestamp
    tipo_ordem_atual = tipo_ordem
    ordem_em_andamento = True
    ultima_ordem_timestamp = time.time()
    print(f"\n📤 Enviando ORDEM REAL: {tipo_ordem} | Valor: R${stake_atual:.2f}")
    contrato = {
        "buy": 1,
        "price": stake_atual,
        "parameters": {
            "amount": stake_atual,
            "basis": "stake",
            "contract_type": tipo_ordem,
            "currency": "USD",
            "duration": 1,
            "duration_unit": "t",
            "symbol": SIMBOLO
        }
    }
    ws.send(json.dumps(contrato))

# === CONSULTAR CONTRATO ===
def consultar_contrato(contract_id):
    consulta = {"proposal_open_contract": 1, "contract_id": contract_id}
    ws.send(json.dumps(consulta))

# === AO RECEBER MENSAGEM ===
def on_message(wsapp, message):
    global precos, lucro_total, ordem_em_andamento, ultimo_contract_id, stake_atual

    try:
        data = json.loads(message)

        if lucro_total >= META_LUCRO:
            print("\n🏁 META DE LUCRO ALCANÇADA!")
            wsapp.close()
            return

        if lucro_total <= -abs(STOP_LOSS):
            print("\n🛑 STOP LOSS ATINGIDO!")
            wsapp.close()
            return

        if data.get("msg_type") == "authorize":
            print("✅ Autenticado.")
            wsapp.send(json.dumps({"ticks": SIMBOLO}))
            return

        if data.get("msg_type") == "buy":
            ultimo_contract_id = data["buy"]["contract_id"]
            print("📨 Contrato enviado.")
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
                # Soros: aumenta após win, reseta após loss
                if lucro > 0:
                    stake_atual += lucro
                else:
                    stake_atual = STAKE_INICIAL
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
                ema = calculate_ema(serie, 14).iloc[-1]
                rsi = calculate_rsi(serie, 14).iloc[-1]
                decisao = decide_trade(preco, ema, rsi, serie)
                print(f"📊 Preço: {preco:.2f} | EMA: {ema:.2f} | RSI: {rsi:.2f} → {decisao}")
                if decisao in ["CALL", "PUT"]:
                    tempo_esperado = time.time() - ultima_ordem_timestamp
                    if tempo_esperado >= 30:
                        enviar_ordem_real(decisao)
                    else:
                        print(f"⏳ Aguardando {30 - int(tempo_esperado)}s para nova entrada...")
            else:
                print(f"⏳ Coletando dados... ({len(precos)}/50)")

    except Exception as e:
        print("⚠️ Erro durante execução:", e)

# === CONEXÃO WEBSOCKET ===
def on_open(wsapp):
    wsapp.send(json.dumps({"authorize": TOKEN}))

def start_deriv_bot():
    global ws
    ws = websocket.WebSocketApp(
        "wss://ws.binaryws.com/websockets/v3?app_id=1089",
        on_open=on_open,
        on_message=on_message
    )
    ws.run_forever()

start_deriv_bot()
