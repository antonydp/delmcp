from fastmcp import FastMCP
import requests
import json
import time
from bs4 import BeautifulSoup
from typing import List, Optional, Dict, Any

# Initialize the MCP Server
mcp = FastMCP("Deliveroo Explorer")

# --- SHARED UTILITIES ---

def _get_headers():
    """Restituisce gli header esatti dello script funzionante"""
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Accept-Language': 'it-IT,it;q=0.9',
        'Referer': 'https://deliveroo.it/',
    }

def _get_next_data(url: str, session: requests.Session) -> Optional[Dict]:
    """
    Helper to extract the __NEXT_DATA__ JSON blob.
    Usa la sessione passata per mantenere i cookie.
    """
    try:
        response = session.get(url, headers=_get_headers(), timeout=15)
        
        # Se otteniamo 403 o 429, è un blocco temporaneo
        if response.status_code in [403, 429]:
            print(f"Blocked or Rate Limited: {response.status_code}")
            return None
            
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        script_tag = soup.find('script', id='__NEXT_DATA__')
        
        if script_tag and script_tag.string:
            return json.loads(script_tag.string)
        
        print("Error: __NEXT_DATA__ tag not found.")
        return None
        
    except Exception as e:
        print(f"Connection error processing {url}: {e}")
        return None

# --- MCP TOOLS ---

@mcp.tool()
def search_restaurants(location_url: str) -> str:
    """
    Cerca ristoranti in una data URL di zona Deliveroo.
    Args:
        location_url: L'URL completo della pagina categoria/zona (es. https://deliveroo.it/it/restaurants/...)
    """
    print(f"Scanning: {location_url}")
    
    # Usiamo una sessione anche qui per coerenza
    with requests.Session() as session:
        json_data = _get_next_data(location_url, session)
    
    if not json_data:
        return "Error: Could not fetch data. The page might be blocked or invalid."

    results = []
    
    try:
        # Percorso JSON identico allo script funzionante
        feed = json_data.get('props', {}).get('initialState', {}).get('home', {}).get('feed', {}).get('results', {}).get('data', [])
        
        for section in feed:
            blocks = section.get('blocks', [])
            for block in blocks:
                if 'partner-card' in block.get('rooTemplateId', ''):
                    data = block.get('data', {})
                    
                    name = data.get('partner-name.content', 'Unknown')
                    
                    # Rating
                    raw_rating = data.get('partner-rating.content', '0')
                    try:
                        rating_val = float(raw_rating.split(' ')[0])
                    except (ValueError, IndexError):
                        rating_val = 0.0

                    dist = data.get('distance-presentational.content', '-')
                    
                    # URL Extraction
                    on_tap = data.get('partner-card.on-tap', {})
                    action_params = on_tap.get('action', {}).get('parameters', {})
                    href_partial = action_params.get('restaurant_href')
                    
                    if href_partial:
                        full_url = f"https://deliveroo.it{href_partial}"
                        results.append({
                            "name": name,
                            "rating": rating_val,
                            "distance": dist,
                            "menu_url": full_url
                        })
                        
    except Exception as e:
        return f"Error parsing listing data: {str(e)}"

    if not results:
        return "No restaurants found. Check if the URL is correct or if the area is served."

    return json.dumps(results[:20], indent=2, ensure_ascii=False) # Limitiamo a 20 per non intasare il contesto

@mcp.tool()
def get_restaurant_menu(menu_url: str) -> str:
    """
    Scarica il menu di un ristorante specifico.
    Args:
        menu_url: L'URL ottenuto dalla ricerca (es. https://deliveroo.it/it/menu/...)
    """
    # Ritardo per educazione verso il server
    time.sleep(1.0) 
    
    # Creiamo una sessione dedicata come nello script funzionante "scarica_singolo_menu"
    with requests.Session() as session:
        json_data = _get_next_data(menu_url, session)
        
    if not json_data:
        return "Error: Could not load menu page (Connection failed or Blocked)."

    try:
        # --- LOGICA ESTRATTA DALLO SCRIPT FUNZIONANTE ---
        menu_obj = json_data['props']['initialState']['menuPage']['menu']
        
        # LA CORREZIONE FONDAMENTALE (metas -> root)
        root_data = menu_obj['metas']['root']
        
        raw_items = root_data.get('items', [])
        raw_categories = root_data.get('categories', [])
        
        # Mappa categorie
        category_map = {cat['id']: cat['name'] for cat in raw_categories}

        # Organizziamo i dati per l'LLM
        organized_menu = {}

        for item in raw_items:
            cat_id = item.get('categoryId')
            cat_name = category_map.get(cat_id, "Altro")
            
            if cat_name not in organized_menu:
                organized_menu[cat_name] = []
            
            # Formattazione prezzo come nello script
            price_data = item.get('price', {})
            prezzo = price_data.get('formatted', '?')

            organized_menu[cat_name].append({
                "item": item.get('name'),
                "description": item.get('description'),
                "price": prezzo
            })
            
        return json.dumps(organized_menu, indent=2, ensure_ascii=False)

    except KeyError:
        return "Error: Menu structure not found. The restaurant might be closed right now."
    except Exception as e:
        return f"Error parsing menu JSON: {str(e)}"

import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    mcp.run(transport="sse", host="0.0.0.0", port=port)
