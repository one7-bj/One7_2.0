import dash
from dash import dcc, html, Input, Output, State, dash_table
import dash_bootstrap_components as dbc
import pandas as pd
import pymupdf
from google import genai
import os
import uuid
import requests
from dotenv import load_dotenv
from supabase import create_client
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user
from flask import Flask, request

load_dotenv()

# ========== 1. CONFIG ==========
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CINETPAY_API_KEY = os.getenv("CINETPAY_API_KEY")
CINETPAY_SITE_ID = os.getenv("CINETPAY_SITE_ID")

client = genai.Client(api_key=GEMINI_API_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
response = client.models.generate_content(
    model="gemini-3.6-flash",
    contents="Salut"
)
print(response.text)
server = Flask(__name__)
server.secret_key = os.urandom(24)
app = dash.Dash(__name__, server=server, external_stylesheets=[dbc.themes.BOOTSTRAP])
app.title = "One7 Pro"

login_manager = LoginManager()
login_manager.init_app(server)
login_manager.login_view = '/login'

# ========== 2. AUTH ==========
class User(UserMixin):
    def __init__(self, user_data):
        self.id = user_data['id']
        self.email = user_data['email']
        self.cabinet_id = user_data['cabinet_id']
        self.role = user_data['role']
        self.nom = user_data['nom']

@login_manager.user_loader
def load_user(user_id):
    res = supabase.table("users_cabinet").select("*").eq("id", user_id).single().execute()
    return User(res.data) if res.data else None

# ========== 3. FONCTION IA ==========
def extraire_facture_ia(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    texte = ""
    for page in doc: texte += page.get_text()
    prompt = f"Extrait de ce texte de facture: N° Facture, Date, NIF Fournisseur, Montant HT, Montant TVA. Retourne en JSON. Texte: {texte[:4000]}"
    response = model.generate_content(prompt)
    return pd.DataFrame([eval(response.text.replace("```json","").replace("```",""))])

# ========== 4. LAYOUTS ==========
login_layout = dbc.Container([
    dbc.Row([dbc.Col(dbc.Card([
        dbc.CardBody([
            html.H2("Connexion One7 Pro", className="text-center"),
            dbc.Input(id="login-email", placeholder="Email", type="email", className="mb-3"),
            dbc.Input(id="login-password", placeholder="Mot de passe", type="password", className="mb-3"),
            dbc.Button("Se connecter", id="btn-login", color="primary", className="w-100"),
            html.Div(id="login-output")
        ])
    ], className="mt-5"), width=6)], justify="center")
], fluid=True)

def get_dashboard_layout():
    return dbc.Container([
        dbc.Navbar([
            dbc.Container([
                dbc.NavbarBrand("ONE7 PRO", className="text-white fw-bold"),
                dbc.Nav([dbc.NavItem(dbc.NavLink(id="credits-value", className="text-white")),
                         dbc.NavItem(dbc.NavLink(id="user-email-nav", className="text-white")),
                         dbc.NavItem(dbc.NavLink("Déconnexion", href="/logout", className="text-warning"))], navbar=True)
            ])
        ], color="dark", className="mb-3"),
        
        html.Div(id="alert-credits"),
        
        dbc.Tabs([
            dbc.Tab(label="📊 Traitement Factures", tab_id="tab-traitement"),
            dbc.Tab(label="💳 Recharger Crédits", tab_id="tab-paiement"),
            dbc.Tab(label="👥 Equipe", tab_id="tab-equipe"),
            dbc.Tab(label="📜 Historique", tab_id="tab-historique"),
        ], id="tabs", active_tab="tab-traitement"),
        
        html.Div(id="tab-content", className="mt-4")

    ], fluid=True)

# ========== 5. CALLBACKS PRINCIPAUX ==========
@app.callback(Output('page-content', 'children'), Input('url', 'pathname'))
def display_page(pathname):
    if pathname == "/login" or not current_user.is_authenticated:
        return login_layout
    elif pathname == "/logout":
        logout_user()
        return login_layout
    else:
        return get_dashboard_layout()

@app.callback(
    [Output('user-email-nav', 'children'), Output('credits-value', 'children'), Output('alert-credits', 'children')],
    [Input('url', 'pathname'), Input('tabs', 'active_tab')]
)
def update_nav(pathname, tab):
    if current_user.is_authenticated:
        res = supabase.table("users_cabinet").select("credits_perso").eq("id", current_user.id).single().execute()
        credits = res.data["credits_perso"]
        alert = dbc.Alert(f"⚠️ Il vous reste seulement {credits} crédits !", color="danger", dismissable=True) if credits < 10 else None
        return current_user.email, f"Crédits: {credits}", alert
    return "", "Crédits: 0", None

@app.callback(Output("tab-content", "children"), Input("tabs", "active_tab"))
def render_tab_content(active_tab):
    if active_tab == "tab-traitement":
        return html.Div([
            dcc.Upload(id='upload-pdf', children=dbc.Button("📁 Uploader PDF"), multiple=True),
            dbc.Button("🚀 Lancer le traitement", id="btn-traiter", color="success", className="mt-3"),
            html.Div(id="output-container")
        ])
    elif active_tab == "tab-paiement":
        return dbc.Card(dbc.CardBody([
            html.H4("💳 Recharger mes crédits"),
            dbc.Input(id="input-credits", type="number", value=100),
            dbc.Button("Payer avec Orange/MTN/Carte", id="btn-payer", color="success", className="mt-2"),
            html.Div(id="payment-link-output")
        ]))
    elif active_tab == "tab-equipe" and current_user.role == "Manager":
        return html.Div([
            html.H3("👥 Gestion de l'équipe"),
            dcc.Loading(html.Div(id="table-equipe")),
            dbc.Row([
                dbc.Col(dcc.Dropdown(id="select-collab")),
                dbc.Col(dbc.Input(id="input-transfert", type="number", placeholder="Nb crédits")),
                dbc.Col(dbc.Button("Transférer", id="btn-transfert", color="success"))
            ], className="mt-3"),
            html.Div(id="msg-transfert")
        ])
    elif active_tab == "tab-historique":
        return html.Div([html.H3("📜 Historique"), dcc.Loading(html.Div(id="table-historique"))])
    return "Accès refusé"

# ========== 6. CALLBACK LOGIN ==========
@app.callback(Output("login-output", "children"), Input("btn-login", "n_clicks"), [State("login-email", "value"), State("login-password", "value")])
def login(n, email, password):
    if n:
        try:
            res = supabase.auth.sign_in_with_password({"email": email, "password": password})
            user_data = supabase.table("users_cabinet").select("*").eq("id", res.user.id).single().execute().data
            login_user(User(user_data))
            return dcc.Location(pathname="/", id="redirect")
        except: return dbc.Alert("Email ou mot de passe incorrect", color="danger")

# ========== 7. CALLBACK TRAITEMENT + DÉDUCTION CRÉDIT ==========
@app.callback(
    Output("output-container", "children"),
    Input("btn-traiter", "n_clicks"),
    State("upload-pdf", "contents"),
    prevent_initial_call=True
)
def traiter_factures(n, list_of_contents):
    if not list_of_contents: return dash.no_update
    
    # 1. VÉRIFIER CRÉDITS AVANT DE COMMENCER
    user_res = supabase.table("users_cabinet").select("credits_perso").eq("id", current_user.id).single().execute()
    credits_actuels = user_res.data["credits_perso"]
    nb_factures = len(list_of_contents)
    
    if credits_actuels < nb_factures:
        return dbc.Alert(f"Crédits insuffisants. Il faut {nb_factures} crédits. Il vous reste {credits_actuels}.", color="danger")
    
    # 2. TRAITER CHAQUE FACTURE
    all_df = []
    for i, content in enumerate(list_of_contents):
        content_type, content_string = content.split(',')
        pdf_bytes = base64.b64decode(content_string)
        df_facture = extraire_facture_ia(pdf_bytes)
        df_facture['traite_par'] = current_user.id
        df_facture['cabinet_id'] = current_user.cabinet_id
        all_df.append(df_facture)
    
    df_final = pd.concat(all_df, ignore_index=True)
    
    # 3. DÉDUIRE LES CRÉDITS APRÈS TRAITEMENT RÉUSSI
    supabase.table("users_cabinet").update({"credits_perso": credits_actuels - nb_factures}).eq("id", current_user.id).execute()
    
    # 4. SAUVEGARDER DANS HISTORIQUE
    for _, row in df_final.iterrows():
        supabase.table("historique_traitements").insert({
            "user_id": current_user.id, 
            "cabinet_id": current_user.cabinet_id,
            "n_facture": row['N° Facture'],
            "credits_consomme": 1
        }).execute()
    
    return html.Div([
        dbc.Alert(f"{nb_factures} factures traitées ! {nb_factures} crédits déduits.", color="success"),
        dash_table.DataTable(data=df_final.to_dict('records'), page_size=10),
        dbc.Button("Télécharger Excel DGI", href="/download", color="primary")
    ])

# ========== 8. CALLBACK PAIEMENT CINETPAY ==========
@app.callback(Output('payment-link-output', 'children'), Input('btn-payer', 'n_clicks'), State('input-credits', 'value'))
def initier_paiement(n, nb_credits):
    if n and nb_credits:
        montant = nb_credits * 50
        transaction_id = f"ONE7_{current_user.cabinet_id}_{uuid.uuid4().hex[:8]}"
        payload = {"apikey": CINETPAY_API_KEY, "site_id": CINETPAY_SITE_ID, "transaction_id": transaction_id, "amount": montant, "currency": "XOF", "description": f"{nb_credits} credits", "customer_email": current_user.email, "notify_url": "https://ton-domaine.onrender.com/webhook_cinetpay", "return_url": "https://ton-domaine.onrender.com/"}
        r = requests.post("https://api-checkout.cinetpay.com/v2/payment", json=payload).json()
        if r['code'] == '201':
            supabase.table('transactions').insert({"cabinet_id": current_user.cabinet_id, "transaction_id": transaction_id, "nb_credits": nb_credits, "montant": montant, "statut": "en_attente"}).execute()
            return dbc.Button("Clique ici pour payer", href=r['data']['payment_url'], target="_blank", color="warning")
    return dash.no_update

# ========== 9. CALLBACK EQUIPE + TRANSFERT ==========
@app.callback([Output("table-equipe", "children"), Output("select-collab", "options")], [Input("tabs", "active_tab"), Input("btn-transfert", "n_clicks")])
def charger_equipe(active_tab, n):
    if active_tab == "tab-equipe":
        res = supabase.table("users_cabinet").select("*").eq("cabinet_id", current_user.cabinet_id).execute()
        df = pd.DataFrame(res.data)
        options = [{"label": f"{row['nom']} - {row['credits_perso']} cr", "value": row['id']} for _, row in df.iterrows()]
        table = dash_table.DataTable(data=df.to_dict('records'), columns=[{"name": c, "id": c} for c in df.columns], style_data_conditional=[{'if': {'filter_query': '{credits_perso} < 10'}, 'backgroundColor': '#ffdddd'}])
        return table, options
    return dash.no_update, dash.no_update

@app.callback(Output("msg-transfert", "children"), Input("btn-transfert", "n_clicks"), [State("select-collab", "value"), State("input-transfert", "value")])
def transferer_credits(n, collab_id, nb_credits):
    if n and collab_id and nb_credits:
        try:
            supabase.rpc('transferer_credits', {'manager_id': current_user.id, 'collab_id': collab_id, 'montant': int(nb_credits)}).execute()
            return dbc.Alert("Transfert réussi !", color="success")
        except Exception as e: return dbc.Alert(str(e), color="danger")
    return dash.no_update

# ========== 10. WEBHOOK CINETPAY ==========
@server.route('/webhook_cinetpay', methods=['POST'])
def webhook_cinetpay():
    data = request.json
    if data['cpm_trans_status'] == 'ACCEPTED':
        trans = supabase.table('transactions').select("*").eq("transaction_id", data['cpm_trans_id']).single().execute()
        if trans.data and trans.data['statut'] == 'en_attente':
            # On crédite le MANAGER du cabinet
            manager = supabase.table('users_cabinet').select("id, credits_perso").eq("cabinet_id", trans.data['cabinet_id']).eq("role", "Manager").single().execute()
            nouveau_solde = manager.data['credits_perso'] + trans.data['nb_credits']
            supabase.table('users_cabinet').update({"credits_perso": nouveau_solde}).eq("id", manager.data['id']).execute()
            supabase.table('transactions').update({"statut": "paye"}).eq("transaction_id", data['cpm_trans_id']).execute()
    return "OK", 200

# ========== 11. RUN ==========
app.layout = html.Div([dcc.Location(id='url'), html.Div(id='page-content')])
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
