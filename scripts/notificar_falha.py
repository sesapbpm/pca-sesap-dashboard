from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


destino = os.environ.get("ALERT_EMAIL", "sesapbpm@gmail.com")
senha = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
repositorio = os.environ.get("GITHUB_REPOSITORY", "dashboard-pca-sesap")
execucao = os.environ.get("RUN_URL", "")

if not senha:
    print("GMAIL_APP_PASSWORD não configurada; o GitHub manterá a notificação da execução com falha.")
    raise SystemExit(0)

mensagem = EmailMessage()
mensagem["Subject"] = f"Falha na atualização do dashboard SESAP — {repositorio}"
mensagem["From"] = destino
mensagem["To"] = destino
mensagem.set_content(
    "A atualização automática do dashboard PCA SESAP falhou.\n\n"
    f"Consulte os registros da execução em: {execucao}\n\n"
    "A última versão válida do dashboard foi mantida no ar."
)

with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as servidor:
    servidor.login(destino, senha)
    servidor.send_message(mensagem)

print(f"Alerta enviado para {destino}.")
