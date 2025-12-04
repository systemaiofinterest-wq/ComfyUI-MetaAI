# ComfyUI_MetaAi/nodes.py
import os
import sys
import time
import json
from pathlib import Path
import asyncio
import torch

# Asegúrate de que playwright esté instalado en tu entorno:
# pip install playwright
# playwright install

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# Importar numpy
try:
    import numpy as np
except ImportError:
    import numpy as np

class MetaAiVideoGenerator4x:
    # ------------------------------------------------------------------

    def __init__(self):
        # Directorio de salida: ComfyUI/output/meta_ai_video
        self.output_dir = Path(__file__).parent.parent.parent / "output" / "meta_ai_video"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": "un bosque encantado en estilo anime."}), 
                "timeout": ("INT", {"default": 240, "min": 30, "max": 600}), 
                "aspect_ratio": (["1:1", "16:9", "9:16"], {"default": "1:1"}),
                "force_generation": ("BOOLEAN", {"default": False}), 
            },
            "optional": {
                "profile_name": ("STRING", {"default": "meta_playwright_profile"}),
            }
        }

    # Definimos 4 salidas para las rutas de los videos
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")  
    RETURN_NAMES = ("video_path_1", "video_path_2", "video_path_3", "video_path_4")
    FUNCTION = "generate_videos" 
    CATEGORY = "MetaAI"

    async def generate_videos(self, prompt, timeout, aspect_ratio, force_generation, profile_name="meta_playwright_profile"):
        """
        Genera videos usando Meta AI, asegurando el prompt fijo y descargando por clic.
        Soporta interfaz en Inglés y Español.
        """
        downloaded_paths = []
        
        # --- Lógica del Prompt ---
        full_prompt = "Animate: " + prompt.strip()
        print(f"Prompt final (Fijo + Usuario + Animate): {full_prompt}")
        # -------------------------

        # 1. Configuración de Playwright
        profile_name = profile_name.strip() or "meta_playwright_profile"
        user_data_dir = Path(__file__).parent / profile_name
        user_data_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            async with async_playwright() as p:
                
                # Configuración del Contexto de Playwright
                context = await p.chromium.launch_persistent_context(
                    str(user_data_dir),
                    headless=False,
                    locale="en-US", # Intentamos forzar inglés
                    args=[
                        "--start-maximized",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-features=TranslateUI,msUnifiedAppUIToolbar",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-background-timer-throttling",
                        "--disable-renderer-backgrounding",
                        "--disable-infobars",
                        "--lang=en-US"
                    ],
                    viewport=None,
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                    accept_downloads=True,
                    timeout=30000
                )

                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto("https://www.meta.ai/media  ", timeout=60000)

                # -------------------------------------------------------------------------
                # --- CORRECCIÓN ASPECT RATIO (Copiado lógica robusta de ImageGenerator) ---
                # -------------------------------------------------------------------------
                try:
                    # Intento 1: Buscar el botón directamente por su etiqueta actual
                    current_ratio_element = page.locator(f'div[aria-label="{aspect_ratio}"]')
                    current_ratio_count = await current_ratio_element.count()
                    
                    if current_ratio_count:
                        # Verificar si ya está seleccionado (busca el checkmark SVG)
                        svg_elements = current_ratio_element.locator('svg:not([fill="none"])')
                        is_selected = await svg_elements.count() > 0
                        
                        if not is_selected:
                            # 1. Clic para abrir el menú
                            await current_ratio_element.click(force=True)
                            await page.wait_for_timeout(1000)
                            
                            # 2. Clic en la opción de texto (ESTO FALTABA EN TU CÓDIGO)
                            option = page.locator(f'text={aspect_ratio}')
                            await option.wait_for(state="visible", timeout=5000)
                            await option.click(force=True)
                    else:
                        # Fallback: Si el botón actual tiene otro nombre (ej. está en 16:9 y queremos 1:1)
                        # Buscamos cualquier botón de ratio conocido para abrir el menú
                        fallback_ratios = ["1:1", "16:9", "9:16", "4:3", "3:4"]
                        for r in fallback_ratios:
                            btn = page.locator(f'div[aria-label="{r}"]')
                            btn_count = await btn.count()
                            
                            if btn_count and await btn.is_visible():
                                # Abrir menú
                                await btn.click(force=True)
                                await page.wait_for_timeout(500)
                                
                                # Seleccionar el ratio deseado
                                target = page.locator(f'text={aspect_ratio}')
                                target_count = await target.count()
                                if target_count:
                                    await target.click(force=True)
                                    break
                except Exception as e:
                    print(f"[WARN] Aspect ratio '{aspect_ratio}' error: {e}", file=sys.stderr)
                # -------------------------------------------------------------------------


                # --- Rellenar prompt y Enviar ---
                try:
                    selector_input = 'div[role="textbox"][contenteditable="true"]'
                    await page.wait_for_selector(selector_input, state="visible", timeout=30000)
                    
                    await page.click(selector_input) # Asegurar foco
                    await page.wait_for_timeout(500)
                    
                    # Limpiar campo (Select all + backspace es más seguro que fill vacío)
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Backspace")

                    if full_prompt:
                        await page.keyboard.insert_text(full_prompt)
                        await page.wait_for_timeout(500)
                        
                        if force_generation:
                            await page.keyboard.insert_text(" ")
                            await page.wait_for_timeout(100)
                            await page.keyboard.press("Backspace")
                            
                        await page.keyboard.press("Enter")
                        print("[INFO] Comando de generación enviado.")
                except PlaywrightTimeoutError:
                    print("[WARN] Campo de prompt no encontrado a tiempo", file=sys.stderr)


                # --- Esperar y descargar videos ---
                if full_prompt:
                    try:
                        print(f"[INFO] Esperando generación de videos (timeout: {timeout}s)...")
                        
                        # Esperar a que aparezcan resultados.
                        await page.wait_for_function(
                            """() => {
                                // Busca elementos de lista que contengan 'Meta AI' en su etiqueta (Inglés o Español)
                                const els = document.querySelectorAll('div[role="listitem"][aria-label*="Meta AI"] img');
                                return els.length >= 4;
                            }""",
                            timeout=timeout * 1000
                        )
                        print("[INFO] Generación detectada. Preparando descarga...")
                        
                        # Selector híbrido Inglés/Español para el botón de descarga
                        selector_download_button = 'div[aria-label="Download media"], div[aria-label="Descargar contenido multimedia"]'
                        
                        try:
                            await page.wait_for_selector(selector_download_button, state="visible", timeout=15000)
                        except:
                            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                            await page.wait_for_timeout(1000)

                        buttons = await page.query_selector_all(selector_download_button)
                        print(f"[DEBUG] Encontrados {len(buttons)} botones de descarga totales.")
                        
                        target_buttons = buttons[-4:] if len(buttons) >= 4 else buttons
                        
                        # Descargar
                        for i, btn in enumerate(target_buttons, 1):
                            try:
                                await page.wait_for_timeout(1000) # Estabilidad

                                async with page.expect_download(timeout=20000) as download_info:
                                    if await btn.is_visible():
                                        await btn.scroll_into_view_if_needed()
                                        await btn.hover()
                                        await btn.click(force=True)
                                    else:
                                        print(f"[WARN] Botón {i} no visible, saltando.")
                                        continue
                                    
                                download_object = await download_info.value
                                
                                if download_object:
                                    suggested_filename = download_object.suggested_filename
                                    if not suggested_filename.lower().endswith(('.mp4', '.webm', '.gif')):
                                        suggested_filename = suggested_filename.split('.')[0] + '.mp4'

                                    safe_name = f"meta_ai_video_{i}_{int(time.time())}.mp4"
                                    save_path = self.output_dir / safe_name
                                    
                                    await download_object.save_as(str(save_path.resolve()))
                                    downloaded_paths.append(str(save_path.resolve()))
                                    print(f"[SUCCESS] Video {i} guardado: {save_path.name}")
                                else:
                                    print(f"[ERROR] Objeto de descarga vacío para video {i}")

                            except Exception as e:
                                print(f"[WARN] Fallo descargando video {i}: {e}")

                        # Llenar con cadenas vacías si se descargaron menos de 4 videos
                        while len(downloaded_paths) < 4:
                            downloaded_paths.append("")

                        # --- Eliminar chat en bucle hasta eliminar todos los chats ---
                        max_attempts = 50  # Limitar intentos para evitar bucles infinitos
                        attempts = 0
                        
                        while attempts < max_attempts:
                            try:
                                # Verificar si hay botones de menú disponibles
                                menu_btn = page.locator('div[aria-label*="More options"]').last
                                menu_btns_count = await menu_btn.count()
                                
                                if menu_btns_count == 0:
                                    print(f"[INFO] No se encontraron más chats para eliminar. Total intentos: {attempts}")
                                    break
                                
                                print(f"[INFO] Encontrado chat disponible. Eliminando...")
                                
                                # Hacer clic en el botón de menú
                                await menu_btn.click(force=True)
                                await asyncio.sleep(1)

                                # Hacer clic en la opción de eliminar chat
                                delete_opt = page.locator('div[role="menuitem"]:has-text("Delete chat")').first
                                if not await delete_opt.is_visible():
                                    delete_opt = page.locator('text="Delete chat"').first
                                if await delete_opt.is_visible():
                                    await delete_opt.click(force=True)
                                    await asyncio.sleep(1)

                                    # Confirmar la eliminación
                                    confirm = page.locator('div[aria-label="Delete"]').first
                                    if not await confirm.is_visible():
                                        confirm = page.locator('span:text-is("Delete")').last
                                    if await confirm.is_visible():
                                        await confirm.click(force=True)
                                    
                                    # Esperar un poco para que se complete la eliminación
                                    await page.wait_for_timeout(2000)
                                    
                                    # Volver a verificar si hay más chats después de eliminar
                                    continue  # Continuar con la siguiente iteración del bucle
                                else:
                                    print(f"[WARN] Opción de eliminar chat no visible, intento {attempts + 1}")
                                    attempts += 1
                                    continue
                                    
                            except Exception as e:
                                print(f"[WARN] Error en el proceso de eliminación de chat #{attempts + 1}: {e}", file=sys.stderr)
                                attempts += 1
                                continue
                        
                        if attempts >= max_attempts:
                            print(f"[WARN] Se alcanzó el límite de intentos ({max_attempts}) para eliminar chats.")

                    except PlaywrightTimeoutError:
                        print("[WARN] Timeout: no se generaron los videos a tiempo", file=sys.stderr)
                        while len(downloaded_paths) < 4:
                            downloaded_paths.append("")

                else:
                    await page.wait_for_timeout(timeout * 1000)
                    while len(downloaded_paths) < 4:
                        downloaded_paths.append("")


                # Cerrar el navegador
                print("Cerrando navegador...")
                try:
                    await context.close()
                except Exception as e:
                    print(f"[WARN] Error al cerrar contexto: {e}", file=sys.stderr)

                # 3. Devolver las rutas de los videos
                print("--- RUTAS FINALES DEVUELTAS AL NODO ---")
                for idx, path in enumerate(downloaded_paths[:4]):
                    print(f"Video Path {idx+1}: {path or '[VACÍO]'}") 
                print("---------------------------------------")
                
                return tuple(downloaded_paths[:4])

        except Exception as e:
            print(f"[ERROR] Error crítico en la función generate_videos: {e}", file=sys.stderr)
            return ("", "", "", "")


# Registro del nodo
NODE_CLASS_MAPPINGS = {
    "MetaAiVideoGenerator4x": MetaAiVideoGenerator4x
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MetaAiVideoGenerator4x": "Meta AI Video x4 Generator"
}