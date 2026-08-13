"""
Tela de login e controle de sessão do Cota RMC — portado do módulo de
autenticação do PEX 2.0 (etl/autenticacao.py: fundo gradiente navy/verde,
partículas animadas em canvas, card branco, botão com brilho no hover),
adaptado para o modelo de login deste projeto: CNPJ + senha, onde a senha
determina o perfil (consultor ou diretor) em vez de usuário nominal.

Credenciais em `.streamlit/secrets.toml` -> seção [auth] (cnpj/
senha_consultor/senha_diretor) — nunca hardcoded aqui. Ver
`.streamlit/secrets.toml.example`.
"""
from __future__ import annotations

import re

import streamlit as st
import streamlit.components.v1 as components
from streamlit_cookies_manager import CookieManager

from modules.styles import GREEN, NAVY

PERFIL_CONSULTOR = "consultor"
PERFIL_DIRETOR = "diretor"

# cookie guarda só o CNPJ (não é secreto — é o mesmo pra todos os
# consultores), nunca senha nem token de sessão. Prefixo evita colisão com
# outros apps de Mariano no mesmo domínio (Streamlit Community Cloud).
_COOKIE_PREFIX = "cota_rmc/"
_COOKIE_CNPJ = "cnpj_lembrado"


# --- sessão ---

def is_authenticated() -> bool:
    return bool(st.session_state.get("cotarmc_autenticado"))


def current_profile() -> str | None:
    return st.session_state.get("cotarmc_perfil")


def logout() -> None:
    st.session_state.pop("cotarmc_autenticado", None)
    st.session_state.pop("cotarmc_perfil", None)


def get_cookies() -> CookieManager:
    return CookieManager(prefix=_COOKIE_PREFIX)


# --- CNPJ: formatação progressiva (só reformata no on_change, não por tecla) ---

def _formatar_cnpj_progressivo(digitos: str) -> str:
    d = digitos
    if len(d) <= 2:
        return d
    if len(d) <= 5:
        return f"{d[:2]}.{d[2:]}"
    if len(d) <= 8:
        return f"{d[:2]}.{d[2:5]}.{d[5:]}"
    if len(d) <= 12:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:]}"
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}"


def _extrair_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")[:14]


def _on_change_usuario() -> None:
    digitos = _extrair_digitos(st.session_state.get("login_usuario", ""))
    st.session_state["login_usuario"] = _formatar_cnpj_progressivo(digitos)


def _validar(digitos_cnpj: str, senha: str) -> tuple[str | None, str | None]:
    auth = st.secrets.get("auth", {})
    if not digitos_cnpj or not senha:
        return None, "Preencha usuário e senha."
    if digitos_cnpj != auth.get("cnpj"):
        return None, "CNPJ não encontrado."
    if senha == auth.get("senha_diretor"):
        return PERFIL_DIRETOR, None
    if senha == auth.get("senha_consultor"):
        return PERFIL_CONSULTOR, None
    return None, "Senha incorreta."


# --- fundo animado (canvas de partículas) — via components.html porque scripts
# soltos dentro de st.markdown não têm execução garantida pelo Streamlit; o
# iframe do componente é reposicionado em tela cheia, atrás de tudo, via CSS
# abaixo. ---

_CANVAS_HTML = """
<html><head><style>
html, body { margin:0; padding:0; overflow:hidden; background:transparent; }
canvas { display:block; width:100%; height:100%; }
</style></head>
<body>
<canvas id="login-canvas"></canvas>
<script>
  const canvas = document.getElementById('login-canvas');
  const ctx = canvas.getContext('2d');
  let w, h, particles = [], mouse = { x: -999, y: -999 };

  function resize() { w = canvas.width = window.innerWidth; h = canvas.height = window.innerHeight; }
  resize();
  window.addEventListener('resize', () => { resize(); particles = []; seed(); });

  function seed() {
    const n = Math.round((w * h) / 9000);
    for (let i = 0; i < n; i++) {
      particles.push({ x: Math.random() * w, y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.3, vy: (Math.random() - 0.5) * 0.3 });
    }
  }
  seed();

  window.addEventListener('mousemove', (e) => { mouse.x = e.clientX; mouse.y = e.clientY; });
  window.addEventListener('mouseleave', () => { mouse.x = -999; mouse.y = -999; });

  function tick() {
    ctx.clearRect(0, 0, w, h);
    for (const p of particles) {
      p.x += p.vx; p.y += p.vy;
      if (p.x < 0 || p.x > w) p.vx *= -1;
      if (p.y < 0 || p.y > h) p.vy *= -1;
      const dx = mouse.x - p.x, dy = mouse.y - p.y, dist = Math.hypot(dx, dy);
      if (dist < 80) { p.x -= dx * 0.02; p.y -= dy * 0.02; }
    }
    ctx.fillStyle = 'rgba(255,255,255,0.55)';
    for (const p of particles) { ctx.beginPath(); ctx.arc(p.x, p.y, 1.4, 0, 7); ctx.fill(); }
    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const dx = particles[i].x - particles[j].x, dy = particles[i].y - particles[j].y, d = Math.hypot(dx, dy);
        if (d < 95) {
          ctx.strokeStyle = 'rgba(255,255,255,' + (0.18 * (1 - d / 95)) + ')';
          ctx.lineWidth = 0.6;
          ctx.beginPath();
          ctx.moveTo(particles[i].x, particles[i].y);
          ctx.lineTo(particles[j].x, particles[j].y);
          ctx.stroke();
        }
      }
    }
    requestAnimationFrame(tick);
  }
  tick();
</script>
</body></html>
"""


def _injetar_css_login() -> None:
    st.markdown(f"""
    <style>
    header[data-testid="stHeader"] {{ display: none !important; }}
    div[data-testid="stAppViewContainer"] {{ background: linear-gradient(135deg, {GREEN} 0%, {NAVY} 100%); }}

    /* iframe do canvas de partículas: fixado em tela cheia, atrás de tudo
       (z-index 0). Sem pointer-events:none aqui de propósito — se o iframe
       não recebe eventos de mouse, o canvas dentro dele não recebe
       mousemove e a repulsão das partículas para de funcionar (bug já visto
       no PEX 2.0). O data-testid="stIFrame" fica no próprio <iframe> nessa
       versão do Streamlit, não numa <div> wrapper (outro bug já visto lá:
       seletor errado deixava isso sem efeito nenhum). */
    iframe[data-testid="stIFrame"] {{
        position: fixed !important; inset: 0 !important;
        width: 100vw !important; height: 100vh !important;
        border: none !important; z-index: 0;
    }}

    /* conteúdo real (logo/headline/card) centralizado, por cima do canvas —
       wrapper próprio (não o container nativo do Streamlit, que resiste a
       override de display/justify-content por causa da especificidade do
       CSS dele) */
    div[class*="st-key-cotalogin-center-wrap"] {{
        position: fixed !important; inset: 0 !important; z-index: 1;
        display: flex !important; flex-direction: column !important;
        align-items: center !important; justify-content: center !important;
        overflow-y: auto !important;
    }}

    .cotalogin-logo {{
        width: 72px; height: 72px; border-radius: 50%; background: #ffffff;
        border: 3px solid {GREEN}; display: flex; align-items: center; justify-content: center;
        font-size: 20px; font-weight: 800; color: {NAVY}; margin: 0 auto 20px;
    }}
    .cotalogin-headline {{
        font-size: 22px; font-weight: 500; color: #ffffff; text-align: center;
        line-height: 1.3; margin: 0 0 24px;
    }}
    .cotalogin-headline span {{ opacity: .8; font-weight: 800; }}

    /* card branco: aplicado ao container nativo (via key) que envolve os campos */
    div[class*="st-key-cotalogin-card"] {{
        background-color: #ffffff !important; border-radius: 14px !important;
        padding: 28px !important; width: 300px; margin: 0 auto; box-sizing: border-box;
        box-shadow: 0 8px 24px rgba(0,0,0,0.18);
    }}
    div[class*="st-key-cotalogin-card"] label p {{ font-size: 12px !important; color: #7A8699 !important; }}
    div[class*="st-key-cotalogin-card"] input {{
        border: 1.5px solid #C7CDD6 !important; border-radius: 7px !important;
        font-size: 13px !important; color: {NAVY} !important; background-color: #ffffff !important;
    }}
    div[class*="st-key-cotalogin-card"] input:focus {{ border-color: {NAVY} !important; }}

    /* ícone nativo de mostrar/ocultar senha do Streamlit (embutido no campo
       type="password") — só ajusta a cor pra combinar com o resto do card,
       sem reimplementar o toggle. */
    div[class*="st-key-cotalogin-card"] input + button[aria-label="Show password"],
    div[class*="st-key-cotalogin-card"] input + button[aria-label="Hide password"] {{
        color: #7A8699 !important;
    }}

    /* botão "Entrar": navy cheio + brilho diagonal no hover, igual ao protótipo */
    div[class*="st-key-cotalogin-card"] div[data-testid="stButton"]:has(button[kind="primary"]) {{
        position: relative; overflow: hidden; border-radius: 8px; margin-top: 6px;
    }}
    div[class*="st-key-cotalogin-card"] button[kind="primary"] {{
        background-color: {NAVY} !important; border: none !important; color: #ffffff !important;
        padding: 12px !important; border-radius: 8px !important; font-weight: 700 !important;
        box-shadow: 0 2px 8px rgba(23,55,94,0.28) !important;
        transition: transform .15s ease, box-shadow .15s ease !important;
    }}
    div[class*="st-key-cotalogin-card"] button[kind="primary"]:hover {{
        transform: translateY(-1px); box-shadow: 0 4px 16px rgba(23,55,94,0.4) !important;
    }}
    div[class*="st-key-cotalogin-card"] div[data-testid="stButton"]:has(button[kind="primary"])::after {{
        content: ""; position: absolute; top: 0; left: -60%; width: 40%; height: 100%;
        background: linear-gradient(120deg, transparent, rgba(141,198,63,0.55), transparent);
        transform: skewX(-20deg); transition: left .5s ease; pointer-events: none;
    }}
    div[class*="st-key-cotalogin-card"] div[data-testid="stButton"]:has(button[kind="primary"]):hover::after {{
        left: 130%;
    }}
    </style>
    """, unsafe_allow_html=True)
    components.html(_CANVAS_HTML, height=1, scrolling=False)


def render_login_screen(app_name: str, cookies: CookieManager) -> None:
    cnpj_salvo = cookies.get(_COOKIE_CNPJ) or ""
    if "login_usuario" not in st.session_state:
        st.session_state["login_usuario"] = _formatar_cnpj_progressivo(_extrair_digitos(cnpj_salvo))
    if "login_lembrar" not in st.session_state:
        st.session_state["login_lembrar"] = bool(cnpj_salvo)

    _injetar_css_login()

    logo_iniciais = "".join(palavra[0] for palavra in app_name.split()[:2]).upper()

    with st.container(key="cotalogin-center-wrap"):
        st.markdown(f'<div class="cotalogin-logo">{logo_iniciais}</div>', unsafe_allow_html=True)
        st.markdown(
            f'<p class="cotalogin-headline">Bem-vindo ao <span>{app_name}</span></p>',
            unsafe_allow_html=True,
        )

        with st.container(key="cotalogin-card"):
            st.text_input(
                "Usuário", key="login_usuario", on_change=_on_change_usuario,
                placeholder="00.000.000/0000-00",
            )

            st.text_input("Senha", key="login_senha", type="password")

            st.checkbox("Lembrar-me", key="login_lembrar")

            entrar = st.button("Entrar", key="cotalogin_entrar", type="primary", use_container_width=True)

            if entrar:
                digitos = _extrair_digitos(st.session_state.get("login_usuario", ""))
                senha = st.session_state.get("login_senha", "")
                perfil, erro = _validar(digitos, senha)
                if erro:
                    st.session_state["cotalogin_erro"] = erro
                else:
                    if st.session_state.get("login_lembrar"):
                        cookies[_COOKIE_CNPJ] = digitos
                    elif _COOKIE_CNPJ in cookies:
                        del cookies[_COOKIE_CNPJ]
                    cookies.save()
                    st.session_state["cotarmc_autenticado"] = True
                    st.session_state["cotarmc_perfil"] = perfil
                    st.session_state.pop("cotalogin_erro", None)
                    st.rerun()

            if st.session_state.get("cotalogin_erro"):
                st.error(st.session_state["cotalogin_erro"])


def render_logout_sidebar() -> None:
    with st.sidebar:
        st.markdown("<div style='margin-top:20px; border-top:1px solid #E4E7EB; padding-top:12px;'></div>",
                     unsafe_allow_html=True)
        perfil = current_profile()
        if perfil:
            st.caption(f"Perfil: {perfil.capitalize()}")
        if st.button("Sair", key="cotarmc_logout", use_container_width=True):
            logout()
            st.rerun()
