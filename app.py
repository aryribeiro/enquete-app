import streamlit as st
import pandas as pd
import time
from datetime import datetime
import hashlib
import json
import os

# Configurações iniciais
st.set_page_config(
    page_title="Enquete App - A sua enquete em tempo real",
    page_icon="📊",
    layout="wide",
)

st.markdown("""
<style>
    .main {
        background-color: #ffffff;
        color: #333333;
    }
    .block-container {
        padding-top: 1rem;
        padding-bottom: 0rem;
    }
    /* Esconde completamente todos os elementos da barra padrão do Streamlit */
    header {display: none !important;}
    footer {display: none !important;}
    #MainMenu {display: none !important;}
    /* Remove qualquer espaço em branco adicional */
    div[data-testid="stAppViewBlockContainer"] {
        padding-top: 0 !important;
        padding-bottom: 0 !important;
    }
    div[data-testid="stVerticalBlock"] {
        gap: 0 !important;
        padding-top: 0 !important;
        padding-bottom: 0 !important;
    }
    /* Remove quaisquer margens extras */
    .element-container {
        margin-top: 0 !important;
        margin-bottom: 0 !important;
    }
</style>
""", unsafe_allow_html=True)

# Função para criar hash da senha
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Caminhos dos arquivos
DATA_FILE = "enquete_dados.json"
CONFIG_FILE = "enquete_config.json"
RESULTS_FILE = "enquete_resultados.json"

# Inicialização dos arquivos se não existirem
if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "w") as f:
        json.dump({
            "senha_professor": hash_password("admin123"),  # Senha padrão
            "enquete_ativa": False,
            "ultima_atualizacao": str(datetime.now())
        }, f)

if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({
            "pergunta": "",
            "opcoes": ["", "", "", "", ""]
        }, f)

if not os.path.exists(RESULTS_FILE):
    with open(RESULTS_FILE, "w") as f:
        json.dump({
            "votos": [0, 0, 0, 0, 0],
            "total_votos": 0
        }, f)

# Função para carregar configurações
def carregar_config():
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

# Função para salvar configurações
def salvar_config(config):
    config["ultima_atualizacao"] = str(datetime.now())
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)

# Função para carregar dados da enquete
def carregar_dados_enquete():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

# Função para salvar dados da enquete
def salvar_dados_enquete(dados):
    with open(DATA_FILE, "w") as f:
        json.dump(dados, f)

# Função para carregar resultados
def carregar_resultados():
    with open(RESULTS_FILE, "r") as f:
        return json.load(f)

# Função para salvar resultados
def salvar_resultados(resultados):
    with open(RESULTS_FILE, "w") as f:
        json.dump(resultados, f)

# Função para resetar votos
def resetar_votos():
    resultados = {"votos": [0, 0, 0, 0, 0], "total_votos": 0}
    salvar_resultados(resultados)

# Interface principal
def main():
    # Inicializar estado da sessão
    if 'modo' not in st.session_state:
        st.session_state.modo = 'aluno'
    if 'voto_registrado' not in st.session_state:
        st.session_state.voto_registrado = False
    if 'ultima_verificacao' not in st.session_state:
        st.session_state.ultima_verificacao = str(datetime.now())
    
    # Sidebar para troca de modo
    with st.sidebar:
        st.title("Navegação")
        if st.button("Modo Professor"):
            st.session_state.modo = 'login_professor'
        if st.button("Modo Aluno"):
            st.session_state.modo = 'aluno'
            st.session_state.voto_registrado = False
    
    # Verificar o modo atual
    if st.session_state.modo == 'login_professor':
        mostrar_tela_login()
    elif st.session_state.modo == 'professor':
        mostrar_tela_professor()
    else:
        mostrar_tela_aluno()

# Tela de login do professor
def mostrar_tela_login():
    st.title("🔐 Login do Professor")
    
    senha = st.text_input("Senha", type="password")
    
    if st.button("Entrar"):
        config = carregar_config()
        if hash_password(senha) == config["senha_professor"]:
            st.session_state.modo = 'professor'
            st.success("Login realizado com sucesso!")
            time.sleep(1)
            st.rerun()
        else:
            st.error("Senha incorreta!")

# Tela do professor
def mostrar_tela_professor():
    st.title("Painel do Professor")
    
    config = carregar_config()
    dados_enquete = carregar_dados_enquete()
    resultados = carregar_resultados()
    
    # Formulário para criar/editar enquete
    with st.form("enquete_form"):
        pergunta = st.text_input("Pergunta da Enquete", value=dados_enquete["pergunta"])
        
        st.subheader("Opções de Resposta")
        opcoes = []
        for i in range(5):
            opcao = st.text_input(f"Opção {i+1}", value=dados_enquete["opcoes"][i])
            opcoes.append(opcao)
        
        col1, col2 = st.columns(2)
        with col1:
            submit = st.form_submit_button("Salvar e Ativar Enquete")
        with col2:
            reset = st.form_submit_button("Resetar Votos")
            
    if reset:
        resetar_votos()
        st.success("Votos resetados com sucesso!")
        time.sleep(1)
        st.rerun()
            
    if submit:
        # Salvar dados da enquete
        dados_enquete = {"pergunta": pergunta, "opcoes": opcoes}
        salvar_dados_enquete(dados_enquete)
        
        # Ativar enquete
        config["enquete_ativa"] = True
        salvar_config(config)
        
        st.success("Enquete salva e ativada com sucesso!")
        time.sleep(1)
        st.rerun()
    
    # Botão para desativar enquete
    if config["enquete_ativa"]:
        if st.button("Desativar Enquete"):
            config["enquete_ativa"] = False
            salvar_config(config)
            st.success("Enquete desativada!")
            time.sleep(1)
            st.rerun()
    
    # Mostrar status da enquete
    st.subheader("Status da Enquete")
    if config["enquete_ativa"]:
        st.success("Enquete ATIVA")
    else:
        st.error("Enquete INATIVA")
    
    # Mostrar resultados da votação
    if config["enquete_ativa"]:
        mostrar_resultados(dados_enquete, resultados, refresh=True)

# Tela do aluno
def mostrar_tela_aluno():
    config = carregar_config()
    
    # Verificar se há uma enquete ativa
    if not config["enquete_ativa"]:
        st.title("⌛ Aguardando Nova Enquete")
        st.info("O professor ainda não iniciou uma nova enquete. Aguarde...")
        st.empty()
        
        # Atualizar a página automaticamente
        time.sleep(3)
        st.rerun()
        return
    
    # Carregar dados da enquete
    dados_enquete = carregar_dados_enquete()
    resultados = carregar_resultados()
    
    st.title("📊 Participe da enquete abaixo:")
    st.header(dados_enquete["pergunta"])
    
    # Verificar se o aluno já votou
    if st.session_state.voto_registrado:
        st.success("Seu voto foi registrado com sucesso!")
        mostrar_resultados(dados_enquete, resultados)
    else:
        # Exibir opções para votação
        opcoes_validas = [opt for opt in dados_enquete["opcoes"] if opt.strip()]
        if opcoes_validas:
            opcao = st.radio("Escolha uma opção:", opcoes_validas)
            
            if st.button("Votar"):
                # Registrar voto
                indice = dados_enquete["opcoes"].index(opcao)
                resultados["votos"][indice] += 1
                resultados["total_votos"] += 1
                salvar_resultados(resultados)
                
                st.session_state.voto_registrado = True
                st.success("Voto registrado com sucesso!")
                time.sleep(1)
                st.rerun()
        else:
            st.warning("O professor ainda não definiu as opções de resposta.")

# Função para exibir resultados com barras horizontais
def mostrar_resultados(dados_enquete, resultados, refresh=False):
    st.subheader("Resultados da Votação")
    
    total_votos = resultados["total_votos"]
    
    if total_votos == 0:
        st.info("Ainda não há votos registrados.")
        return
    
    # Preparar dados para visualização
    dados = []
    for i, opcao in enumerate(dados_enquete["opcoes"]):
        if opcao.strip():  # Verificar se a opção não está vazia
            votos = resultados["votos"][i]
            percentual = (votos / total_votos) * 100 if total_votos > 0 else 0
            dados.append({"opcao": opcao, "votos": votos, "percentual": percentual})
    
    # Criar dataframe
    df = pd.DataFrame(dados)
    
    # Exibir resultados com barras horizontais
    for _, row in df.iterrows():
        col1, col2 = st.columns([8, 2])
        with col1:
            st.progress(row["percentual"] / 100)
        with col2:
            st.write(f"{row['votos']} ({row['percentual']:.1f}%)")
        st.write(f"**{row['opcao']}**")
    
    st.write(f"**Total de votos: {total_votos}**")
    
    # Atualizar resultados automaticamente para o professor
    if refresh:
        time.sleep(2)
        st.rerun()

if __name__ == "__main__":
    main()

# Rodapé
st.markdown("""
<hr>
<div style="text-align:center; margin-top:40px; padding:10px; color:#000000; font-size:16px;">
    <h4>📊 Enquete App</h4>
            A sua enquete em tempo real<br>
            Por <strong>Ary Ribeiro:</strong> <a href="mailto:aryribeiro@gmail.com">aryribeiro@gmail.com
</div>
""", unsafe_allow_html=True)