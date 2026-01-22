from fastmcp import FastMCP
import requests
import json
import time
from bs4 import BeautifulSoup
from typing import List, Optional, Dict, Any

# Initialize the MCP Server
mcp = FastMCP("Deliveroo Explorer")

# --- SHARED UTILITIES & CONFIG ---

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Accept-Language': 'it-IT,it;q=0.9',
    'Referer': 'https://deliveroo.it/',
    'Upgrade-Insecure-Requests': '1'
}

def _get_next_data(url: str) -> Optional[Dict]:
    """
    Helper to extract the __NEXT_DATA__ JSON blob from Deliveroo pages.
    Includes retry logic for 429 errors.
    """
    session = requests.Session()
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            response = session.get(url, headers=HEADERS, timeout=15)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                script_tag = soup.find('script', id='__NEXT_DATA__')
                if script_tag and script_tag.string:
                    return json.loads(script_tag.string)
                return None
            
            elif response.status_code == 429:
                wait_time = (attempt + 1) * 5
                time.sleep(wait_time)
                continue
            else:
                return None
                
        except Exception as e:
            print(f"Connection error: {e}")
            time.sleep(2)
            
    return None

# --- MCP TOOLS ---

@mcp.tool()
def search_restaurants(location_url: str, min_rating: float = 0.0) -> str:
    """
    Scrapes a Deliveroo listing page to return a list of available restaurants.
    
    Args:
        location_url: The full URL of the Deliveroo category/location page.
        min_rating: Filter out restaurants below this rating (default 0.0).
        
    Returns:
        A JSON string containing a summary of restaurants (Name, ID, Rating, Link).
    """
    print(f"Scanning: {location_url}")
    json_data = _get_next_data(location_url)
    
    if not json_data:
        return "Error: Could not fetch data from Deliveroo. Check the URL."

    results = []
    
    try:
        # Navigate the JSON structure (Matches original script logic)
        feed = json_data.get('props', {}).get('initialState', {}).get('home', {}).get('feed', {}).get('results', {}).get('data', [])
        
        for section in feed:
            blocks = section.get('blocks', [])
            for block in blocks:
                if 'partner-card' in block.get('rooTemplateId', ''):
                    data = block.get('data', {})
                    
                    # Extract Data
                    name = data.get('partner-name.content', 'Unknown')
                    
                    # Rating parsing
                    raw_rating = data.get('partner-rating.content', '0')
                    try:
                        rating_val = float(raw_rating.split(' ')[0])
                    except (ValueError, IndexError):
                        rating_val = 0.0
                    
                    # Filter by rating
                    if rating_val < min_rating:
                        continue

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
        return f"Error parsing data: {str(e)}"

    if not results:
        return "No restaurants found. The page structure might have changed or the location is empty."

    # Return a condensed version for the AI to read easily
    return json.dumps(results, indent=2, ensure_ascii=False)

@mcp.tool()
def get_restaurant_menu(menu_url: str) -> str:
    """
    Fetches the specific menu items for a single restaurant.
    
    Args:
        menu_url: The full URL of the specific restaurant (obtained from search_restaurants).
        
    Returns:
        A JSON string listing the menu categories and items with prices.
    """
    # Polite delay to prevent banning since the AI might click this quickly
    time.sleep(1.5) 
    
    json_data = _get_next_data(menu_url)
    if not json_data:
        return "Error: Could not load menu."

    menu_content = []

    try:
        menu_obj = json_data['props']['initialState']['menuPage']['menu']
        root_data = menu_obj['metas']['root']
        
        raw_items = root_data.get('items', [])
        raw_categories = root_data.get('categories', [])
        
        # Create a lookup map for categories
        category_map = {cat['id']: cat['name'] for cat in raw_categories}

        # Organize by category for the AI
        organized_menu = {}

        for item in raw_items:
            cat_id = item.get('categoryId')
            cat_name = category_map.get(cat_id, "Other")
            
            if cat_name not in organized_menu:
                organized_menu[cat_name] = []
                
            organized_menu[cat_name].append({
                "item": item.get('name'),
                "description": item.get('description'),
                "price": item.get('price', {}).get('formatted', '?')
            })
            
        menu_content = organized_menu

    except KeyError:
        return "Error: Menu structure not found (Restaurant might be closed or page changed)."
    except Exception as e:
        return f"Error parsing menu: {str(e)}"

    return json.dumps(menu_content, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    # This creates a web server on port 8000
    mcp.run(transport="sse")
