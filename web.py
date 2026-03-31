import argparse
import os
import re
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.feirasdobrasil.com.br/2026/"
LOGIN_URL = urljoin(BASE_URL, "login.asp")
LOGIN_ACTION_URL = urljoin(BASE_URL, "assinantes_valida.asp")
CALENDAR_URL = urljoin(BASE_URL, "cal2026.asp")
DEFAULT_OUTPUT_FILE = "feiras_2026.csv"
MONTH_ENTRIES = [
    ("janeiro", "cal2026.asp?mes_evento=janeiro&pagina=1"),
    ("fevereiro", "cal2026.asp?mes_evento=fevereiro&pagina=1"),
    ("março", "cal2026.asp?mes_evento=mar%E7o&pagina=1"),
    ("abril", "cal2026.asp?mes_evento=abril&pagina=1"),
    ("maio", "cal2026.asp?mes_evento=maio&pagina=1"),
    ("junho", "cal2026.asp?mes_evento=junho&pagina=1"),
    ("julho", "cal2026.asp?mes_evento=julho&pagina=1"),
    ("agosto", "cal2026.asp?mes_evento=agosto&pagina=1"),
    ("setembro", "cal2026.asp?mes_evento=setembro&pagina=1"),
    ("outubro", "cal2026.asp?mes_evento=outubro&pagina=1"),
    ("novembro", "cal2026.asp?mes_evento=novembro&pagina=1"),
    ("dezembro", "cal2026.asp?mes_evento=dezembro&pagina=1"),
]


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def strip_trailing_marker(value: str) -> str:
    text = clean_text(value)
    return re.sub(r"\s+[a-zA-Z]$", "", text).strip()


def normalize_edicao(value: str) -> str:
    text = clean_text(value)
    text = re.sub(
        r"\b(\d+\s*[ºª°])(?:\s+[a-z])+\s+(edi[cç][aã]o)\b",
        r"\1 \2",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\b(\d+\s*[ºª°])\s+(edi[cç][aã]o)\b", r"\1 \2", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+[a-zA-Z]$", "", text).strip()
    return text


def fetch_html(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    if not response.encoding:
        response.encoding = "cp1252"
    return response.text


def detect_login_failure(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    title = clean_text(soup.title.get_text(" ", strip=True) if soup.title else "").lower()
    if "login" in title:
        return True
    page_text = clean_text(soup.get_text(" ", strip=True)).lower()
    return "exclusivo para assinantes" in page_text and "digite seus códigos de acesso" in page_text


def login(session: requests.Session, email: str, senha: str) -> None:
    session.get(LOGIN_URL, timeout=30).raise_for_status()
    payload = {
        "email_login2026": email,
        "senha_login2026": senha,
        "ip": "",
    }
    response = session.post(LOGIN_ACTION_URL, data=payload, timeout=30, allow_redirects=True)
    response.raise_for_status()
    if detect_login_failure(response.text):
        raise RuntimeError("Falha no login. Verifique e-mail e senha.")


def extract_field_from_cell(details_cell: BeautifulSoup, label: str) -> str:
    strong = details_cell.find("b", string=re.compile(rf"^\s*{re.escape(label)}\s*$", re.IGNORECASE))
    if strong is None:
        return ""
    pieces = []
    for node in strong.next_siblings:
        if getattr(node, "name", None) == "b":
            break
        if getattr(node, "name", None) == "span":
            classes = node.get("class") or []
            if "verdana15_branco" in classes:
                continue
        pieces.append(clean_text(getattr(node, "get_text", lambda *args, **kwargs: str(node))(" ", strip=True)))
    return clean_text(" ".join(part for part in pieces if part))


def normalize_mes_evento(value: str) -> str:
    text = clean_text(value)
    text = re.sub(r"^[a-z]\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+[a-z]$", "", text, flags=re.IGNORECASE)
    return clean_text(text)


def split_data_evento(data_text: str) -> tuple[str, str]:
    text = clean_text(data_text.lower())
    same_month = re.match(
        r"^(\d{1,2})\s+(?:a|e)\s+(\d{1,2})\s+de\s+([a-zçáàâãéêíóôõú]+)\s+de\s+(\d{4})$",
        text,
    )
    if same_month:
        d1, d2, mes, ano = same_month.groups()
        return f"{d1} de {mes} de {ano}", f"{d2} de {mes} de {ano}"

    cross_month = re.match(
        r"^(\d{1,2})\s+de\s+([a-zçáàâãéêíóôõú]+)\s+a\s+(\d{1,2})\s+de\s+([a-zçáàâãéêíóôõú]+)\s+de\s+(\d{4})$",
        text,
    )
    if cross_month:
        d1, mes1, d2, mes2, ano = cross_month.groups()
        return f"{d1} de {mes1} de {ano}", f"{d2} de {mes2} de {ano}"

    full_range = re.match(
        r"^(\d{1,2}\s+de\s+[a-zçáàâãéêíóôõú]+(?:\s+de\s+\d{4})?)\s+a\s+(\d{1,2}\s+de\s+[a-zçáàâãéêíóôõú]+\s+de\s+\d{4})$",
        text,
    )
    if full_range:
        inicio, fim = full_range.groups()
        if not re.search(r"\bde\s+\d{4}$", inicio):
            ano = re.search(r"\b(\d{4})$", fim)
            if ano:
                inicio = f"{inicio} de {ano.group(1)}"
        return clean_text(inicio), clean_text(fim)

    single_day = re.match(r"^\d{1,2}\s+de\s+[a-zçáàâãéêíóôõú]+\s+de\s+\d{4}$", text)
    if single_day:
        return text, text

    return text, text


def clean_tamanho(value: str) -> str:
    text = clean_text(value)
    text = re.sub(
        r"\(\*{3}\s*expectativa\s+de\s+p[úu]blico\)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return clean_text(text)


def split_cidade_uf(value: str) -> tuple[str, str]:
    text = clean_text(value)
    cidade_uf = text.split(" - ")[0]
    match = re.match(r"^(.*?)/([A-Z]{2})$", cidade_uf)
    if match:
        cidade, uf = match.groups()
        return clean_text(cidade), uf
    return text, ""


def clean_telefone(value: str) -> str:
    text = clean_text(value)
    text = re.sub(r"\s*-\s*$", "", text)
    return clean_text(text)


def extract_site_feira(details_cell: BeautifulSoup) -> str:
    b_site = details_cell.find("b", string=re.compile(r"site da feira:", re.IGNORECASE))
    if b_site is None:
        return ""
    link = b_site.find_next("a", href=True)
    if link is None:
        return ""
    return clean_text(link.get("href", ""))


def extract_abrangencia(details_cell: BeautifulSoup) -> str:
    _, abrangencia = extract_classificacao_evento(details_cell)
    return abrangencia


def normalize_abrangencia(value: str) -> str:
    normalized = clean_text(value).lower()
    normalized = re.sub(r"[^a-záàâãéêíóôõúç ]+", "", normalized).strip()
    if "reginal" in normalized or "regional" in normalized:
        return "Regional"
    if "nacional" in normalized:
        return "Nacional"
    if "municipal" in normalized:
        return "Municipal"
    if any(x in normalized for x in {"internacional", "internacinal", "interncional"}):
        return "Internacional"
    return ""


def extract_classificacao_evento(details_cell: BeautifulSoup) -> tuple[str, str]:
    full_text = clean_text(details_cell.get_text(" ", strip=True))
    header_text = re.split(r"\bTamanho:\b", full_text, flags=re.IGNORECASE)[0].strip()
    header_text = re.split(
        r"\b(Segmento:|Acesso ao Evento:|M[eê]s:|Data:|Local:|Cidade/UF:|Promotor:|Tel:)\b",
        header_text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    if not header_text:
        return "", ""
    parts = [clean_text(part).strip(" -*") for part in re.split(r"\s*/\s*", header_text) if clean_text(part)]
    label_markers = ["segmento:", "acesso ao evento:", "mês:", "mes:", "data:", "local:", "cidade/uf:", "promotor:", "tel:"]
    edicao = ""
    abrangencia = ""
    for part in parts:
        lower = part.lower()
        if any(marker in lower for marker in label_markers):
            continue
        if not edicao:
            cleaned_part = re.sub(r"[^0-9a-záàâãéêíóôõúçºª° ]+", " ", lower)
            cleaned_part = clean_text(cleaned_part)
            has_num = bool(re.search(r"\d", cleaned_part))
            has_edicao_word = "edi" in cleaned_part
            has_ordinal = bool(re.search(r"[ºª°]", cleaned_part))
            is_varias_edicoes = "varias edicoes no ano" in lower or "várias edições no ano" in lower
            has_strict_pattern = bool(re.search(r"\b\d+\s*[ºª°]?\s*edi", cleaned_part)) or bool(
                re.search(r"\b\d+\s*[ºª°]\b", cleaned_part)
            )
            if not is_varias_edicoes and has_num and (has_edicao_word or has_ordinal or has_strict_pattern):
                edicao = normalize_edicao(part)
                continue
        normalized = normalize_abrangencia(part)
        if not abrangencia and normalized:
            abrangencia = normalized
            continue
    return edicao, abrangencia


def is_evento_presencial(evento: dict) -> bool:
    acesso = clean_text(str(evento.get("acesso_evento", ""))).lower()
    return "online" not in acesso


def parse_eventos(html: str, mes_consulta: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    eventos = []
    for nome_cell in soup.select("td.verdana25_cinza"):
        nome_evento = strip_trailing_marker(clean_text(" ".join(nome_cell.stripped_strings)))
        if not nome_evento:
            continue
        table = nome_cell.find_parent("table")
        if table is None:
            continue
        details_cell = None
        for cell in table.select("td.verdana20_cinza"):
            cell_text = clean_text(" ".join(cell.stripped_strings))
            if "Data:" in cell_text and "Cidade/UF:" in cell_text:
                details_cell = cell
                break
        if details_cell is None:
            continue
        mes_evento = normalize_mes_evento(extract_field_from_cell(details_cell, "Mês:"))
        data = extract_field_from_cell(details_cell, "Data:")
        data_inicio, data_fim = split_data_evento(data)
        cidade, uf = split_cidade_uf(extract_field_from_cell(details_cell, "Cidade/UF:"))
        edicao, abrangencia = extract_classificacao_evento(details_cell)
        eventos.append(
            {
                "nome_evento": nome_evento,
                "edicao": edicao,
                "abrangencia": abrangencia,
                "tamanho": clean_tamanho(extract_field_from_cell(details_cell, "Tamanho:")),
                "segmento": extract_field_from_cell(details_cell, "Segmento:"),
                "acesso_evento": extract_field_from_cell(details_cell, "Acesso ao Evento:"),
                "mes_evento": mes_evento,
                "data_inicio": data_inicio,
                "data_fim": data_fim,
                "local": extract_field_from_cell(details_cell, "Local:"),
                "cidade": cidade,
                "uf": uf,
                "promotor": extract_field_from_cell(details_cell, "Promotor:"),
                "telefone": clean_telefone(extract_field_from_cell(details_cell, "Tel:")),
                "site_feira": extract_site_feira(details_cell),
            }
        )
    return eventos


def discover_total_pages(html: str, mes: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    pattern = re.compile(r"cal2026\.asp\?[^\"']*?\bpagina=(\d+)", re.IGNORECASE)
    pages = set()
    for link in soup.select("a[href]"):
        match = pattern.search(link["href"])
        if match:
            pages.add(int(match.group(1)))
    pages_from_links = max(pages) if pages else 1
    page_text = clean_text(soup.get_text(" ", strip=True))
    match_text = re.search(r"página:\s*\d+\s*de\s*(\d+)", page_text, flags=re.IGNORECASE)
    pages_from_text = int(match_text.group(1)) if match_text else 1
    return max(pages_from_links, pages_from_text)


def fetch_calendar_page(session: requests.Session, month_relative_url: str, pagina: int) -> str:
    page_relative_url = re.sub(r"([?&]pagina=)\d+", rf"\g<1>{pagina}", month_relative_url, flags=re.IGNORECASE)
    page_url = urljoin(BASE_URL, page_relative_url)
    response = session.get(page_url, timeout=30)
    response.raise_for_status()
    if not response.encoding:
        response.encoding = "cp1252"
    response_text = response.text
    should_try_fallback = pagina == 1 and ("página:" in response_text.lower())
    if should_try_fallback:
        fallback_params = dict(
            item.split("=", 1) for item in page_relative_url.split("?", 1)[1].split("&") if "=" in item
        )
        fallback_params["pagina"] = str(pagina)
        fallback = session.get(CALENDAR_URL, params=fallback_params, timeout=30)
        fallback.raise_for_status()
        if not fallback.encoding:
            fallback.encoding = "cp1252"
        if len(fallback.text) > len(response_text):
            return fallback.text
    return response_text


def scrape_ano(session: requests.Session) -> list[dict]:
    eventos = []
    print(f"meses detectados: {', '.join(m for m, _ in MONTH_ENTRIES)}")
    for mes, month_relative_url in MONTH_ENTRIES:
        print(f"[{mes}] consultando página 1...")
        html_primeira = fetch_calendar_page(session, month_relative_url, 1)
        if detect_login_failure(html_primeira):
            raise RuntimeError("Sessão sem acesso após login. Não foi possível acessar o calendário completo.")
        total_pages = discover_total_pages(html_primeira, mes)
        print(f"[{mes}] total de páginas: {total_pages}")
        eventos_mes = parse_eventos(html_primeira, mes)
        for pagina in range(2, total_pages + 1):
            print(f"[{mes}] consultando página {pagina}/{total_pages}...")
            html = fetch_calendar_page(session, month_relative_url, pagina)
            eventos_mes.extend(parse_eventos(html, mes))
        eventos_mes_presenciais = [evento for evento in eventos_mes if is_evento_presencial(evento)]
        print(f"[{mes}] registros do mês: {len(eventos_mes_presenciais)} presenciais ({len(eventos_mes)} total)")
        eventos.extend(eventos_mes_presenciais)
    return eventos


def build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Faz login no Feiras do Brasil (2026), extrai todos os eventos do ano e salva em CSV."
    )
    parser.add_argument("--email", default=os.getenv("FEIRAS_EMAIL", ""), help="E-mail do assinante.")
    parser.add_argument("--senha", default=os.getenv("FEIRAS_SENHA", ""), help="Senha do assinante.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_FILE, help="Arquivo CSV de saída.")
    return parser.parse_args()


def main() -> None:
    args = build_args()
    if not args.email or not args.senha:
        raise RuntimeError("Informe credenciais via --email/--senha ou variáveis FEIRAS_EMAIL/FEIRAS_SENHA.")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
    }
    with requests.Session() as session:
        session.headers.update(headers)
        login(session, args.email, args.senha)
        eventos = scrape_ano(session)
    df = pd.DataFrame(eventos)
    df.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"Extração concluída. Total de eventos: {len(eventos)}")
    print(f"CSV gerado em: {args.output}")


if __name__ == "__main__":
    main()
