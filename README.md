# 📊Enquete App | Sua Enquete em Tempo Real

O Enquete App é uma aplicação web construída com Streamlit e Python que permite a criação de enquetes em tempo real. É ideal para salas de aula, apresentações ou qualquer situação onde um feedback rápido do público é necessário.

## Funcionalidades Principais

* **Dois Modos de Usuário**:
    * **Professor**: Controla a enquete.
    * **Aluno**: Participa da enquete.
* **Painel do Professor**:
    * Login seguro com senha (hash SHA256).
    * Criação e edição de enquetes com pergunta e um número flexível de opções de resposta (2 a 10).
    * Ativação e desativação de enquetes.
    * Ao desativar uma enquete, os votos e registros de IP são resetados.
    * Visualização dos resultados da votação em tempo real (auto-refresh).
    * Opção para alterar a senha do professor.
    * Botão de Logout.
* **Interface do Aluno**:
    * Visualização da enquete ativa.
    * Sistema de votação que permite um voto por endereço IP para a enquete ativa.
    * Obtenção do IP do aluno via API externa (`ipify.org`) para controle de voto único.
    * Visualização dos resultados da votação em tempo real (auto-refresh) após ter votado.
    * Botão "Recarregar Enquete" para atualização manual do status da enquete.
    * Tela de "Aguardando Nova Enquete" com auto-refresh para verificar quando uma enquete se torna ativa.
* **Persistência de Dados**:
    * Utiliza um banco de dados **SQLite (`enquete_app_vfinal.db`)** para armazenar:
        * Configurações da aplicação (senha do professor, status da enquete).
        * Definição da enquete ativa (pergunta e opções).
        * Contagem de votos para cada opção.
        * Endereços IP dos participantes que já votaram.
* **Interface Customizada**:
    * Layout limpo e focado, com elementos padrão do Streamlit ocultados (menu, header, footer) para uma experiência mais imersiva.

## Tecnologias Utilizadas

* **Python 3**
* **Streamlit**: Para a interface web interativa.
* **SQLite**: Para armazenamento de dados persistente.
* **Pandas**: Para manipulação e exibição de dados (resultados da enquete).
* **Requests**: Para chamadas HTTP à API de IP.

## Estrutura do Projeto
├── enquete_app_vfinal.db   # Banco de dados SQLite (criado na primeira execução)
└── app.py                  # Código principal da aplicação Streamlit

## Pré-requisitos

* Python 3.7 ou superior.
* `pip` (gerenciador de pacotes Python).

## Instalação e Execução

1.  **Clone o repositório (se aplicável) ou copie o arquivo `app.py`.**

2.  **Crie e ative um ambiente virtual (recomendado):**
    ```bash
    python -m venv venv
    # No Windows:
    # venv\Scripts\activate
    # No macOS/Linux:
    # source venv/bin/activate
    ```

3.  **Instale as dependências:**
    Crie um arquivo `requirements.txt` com o seguinte conteúdo:
    ```txt
    streamlit
    pandas
    requests
    ```
    E então execute:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Execute a aplicação Streamlit:**
    Navegue até o diretório onde `app.py` está localizado e execute:
    ```bash
    streamlit run app.py
    ```
    A aplicação será aberta automaticamente no seu navegador web.

## Configuração Inicial

* Na primeira execução, o banco de dados `enquete_app_vfinal.db` será criado.
* A senha padrão do professor é `admin123`. É altamente recomendável alterá-la através do painel do professor após o primeiro login.

## Como Usar

1.  **Professor**:
    * Acesse o aplicativo.
    * Clique em "Professor" na barra lateral.
    * Faça login com a senha (padrão: `admin123`).
    * No painel do professor:
        * Defina o número de opções de resposta desejado.
        * Digite a pergunta da enquete e as opções de resposta.
        * Clique em "Salvar e Ativar Enquete". Os votos para a nova configuração da enquete são resetados.
        * Monitore os resultados em tempo real.
        * Para encerrar a votação e resetar os votos, clique em "Desativar Enquete".
        * Use o botão "Alterar Senha" para definir uma nova senha.
        * Use "Logout" para retornar à tela de login.

2.  **Aluno**:
    * Acesse o aplicativo. A tela mostrará "Aguardando Nova Enquete" se nenhuma estiver ativa (com auto-refresh).
    * Quando uma enquete estiver ativa, ela será exibida.
    * Selecione uma opção e clique em "Votar".
    * Após votar, os resultados da enquete serão exibidos e atualizados automaticamente.
    * Use o botão "Recarregar Enquete" na barra lateral para forçar uma atualização da página.

## Possíveis Melhorias Futuras

* Suporte para múltiplas enquetes salvas e um histórico de enquetes.
* Exportação de resultados da enquete (ex: para CSV).
* Autenticação de alunos (se necessário para cenários mais controlados).
* Melhorias na interface e experiência do usuário, como feedback visual mais dinâmico.
* Opção para o professor editar uma enquete ativa sem necessariamente resetar todos os votos (ex: corrigir um erro de digitação em uma opção).

## Autor

* **Ary Ribeiro**
* Contato: [aryribeiro@gmail.com](mailto:aryribeiro@gmail.com)