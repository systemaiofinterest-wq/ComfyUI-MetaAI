# ComfyUI_MetaAi/nodes.py
import os
import sys
import time
import json
from pathlib import Path
import asyncio
import torch
from PIL import Image

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

class MetaAiImageGenerator:
    def __init__(self):
        # Directorio de salida en la carpeta principal de ComfyUI
        self.output_dir = Path(__file__).parent.parent.parent / "output" / "meta_ai_image"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "timeout": ("INT", {"default": 120, "min": 10, "max": 300}),
                "aspect_ratio": (["1:1", "16:9", "9:16"], {"default": "1:1"}),
                "force_generation": ("BOOLEAN", {"default": False}),  # Añadido parámetro para forzar generación
            },
            "optional": {
                "profile_name": ("STRING", {"default": "meta_playwright_profile3"}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("preview_images",)
    FUNCTION = "generate_images"
    CATEGORY = "MetaAI"

    async def generate_images(self, prompt, timeout, aspect_ratio, force_generation, profile_name="meta_playwright_profile3"):
        """
        Genera imágenes usando Meta AI y devuelve las imágenes como tensor
        """
        # Aseguramos que el nombre del perfil no esté vacío
        profile_name = profile_name.strip() or "meta_playwright_profile3"

        full_prompt = "Create Image: " + prompt.strip()
        
        # Directorio fijo para el perfil (dentro del directorio del nodo)
        user_data_dir = Path(__file__).parent / profile_name
        user_data_dir.mkdir(parents=True, exist_ok=True)

        downloaded_paths = []

        try:
            async with async_playwright() as p:
                context = await p.chromium.launch_persistent_context(
                    str(user_data_dir),
                    headless=False,
                    locale="en-US",
                    args=[
                        "--start-maximized",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-features=TranslateUI,msUnifiedAppUIToolbar",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-background-timer-throttling",
                        "--disable-renderer-backgrounding",
                        "--disable-features=CalculateNativeWinOcclusion",
                        "--disable-infobars",
                        "--disable-session-crashed-bubble",
                        "--lang=en-US"
                    ],
                    viewport=None,
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                    accept_downloads=True,
                    ignore_default_args=["--enable-automation"],
                    timeout=30000
                )

                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto("https://www.meta.ai/media", timeout=60000)

                # --- Seleccionar aspect ratio ---
                try:
                    current_ratio_element = page.locator(f'div[aria-label="{aspect_ratio}"]')
                    current_ratio_count = await current_ratio_element.count()
                    if current_ratio_count:
                        svg_elements = current_ratio_element.locator('svg:not([fill="none"])')
                        is_selected = await svg_elements.count() > 0
                        if not is_selected:
                            await current_ratio_element.click(force=True)
                            await page.wait_for_timeout(1000)
                            option = page.locator(f'text={aspect_ratio}')
                            await option.wait_for(state="visible", timeout=5000)
                            await option.click(force=True)
                    else:
                        fallback_ratios = ["1:1", "16:9", "9:16", "4:3", "3:4"]
                        for r in fallback_ratios:
                            btn = page.locator(f'div[aria-label="{r}"]')
                            btn_count = await btn.count()
                            if btn_count and await btn.is_visible():
                                await btn.click(force=True)
                                await page.wait_for_timeout(500)
                                target = page.locator(f'text={aspect_ratio}')
                                target_count = await target.count()
                                if target_count:
                                    await target.click(force=True)
                                    break
                except Exception as e:
                    print(f"[WARN] Aspect ratio '{aspect_ratio}': {e}", file=sys.stderr)

                # --- Rellenar prompt ---
                try:
                    selector_input = 'div[role="textbox"][contenteditable="true"]'
                    await page.wait_for_selector(selector_input, state="visible", timeout=30000)
                    await page.click(selector_input)
                    await page.wait_for_timeout(1000)

                    if full_prompt:
                        await page.keyboard.insert_text(full_prompt)
                        await page.wait_for_timeout(500)
                        
                        # Forzar generación si está habilitado
                        if force_generation:
                            # Agregar un carácter único temporal al prompt y luego borrarlo
                            # para forzar la actualización
                            await page.keyboard.insert_text(" ")
                            await page.wait_for_timeout(100)
                            await page.keyboard.press("Backspace")
                        
                        await page.keyboard.press("Enter")
                except PlaywrightTimeoutError:
                    print("[WARN] Campo de prompt no encontrado a tiempo", file=sys.stderr)

                # --- Esperar y descargar imágenes ---
                if full_prompt:
                    try:
                        # Esperar a que aparezcan las imágenes generadas
                        await page.wait_for_function(
                            "() => document.querySelectorAll('div[aria-label=\"Download media\"]').length >= 4",
                            timeout=timeout * 1000
                        )
                        
                        # Buscar imágenes generadas directamente en el DOM
                        image_selectors = [
                            'img[alt="Media generated by meta.ai"]',
                            'div[aria-label="Download media"] img',
                            'img[src*="scontent.feze8-2.fna.fbcdn.net"]'
                        ]
                        
                        for selector in image_selectors:
                            images = await page.query_selector_all(selector)
                            print(f"[DEBUG] Encontradas {len(images)} imágenes con selector: {selector}")
                            if len(images) >= 4:
                                break
                        
                        # Si no encontramos imágenes con download buttons, intentamos capturarlas directamente
                        if len(images) == 0:
                            # Esperar un poco más y luego capturar imágenes visibles
                            await page.wait_for_timeout(5000)
                            images = await page.query_selector_all('img[alt="Media generated by meta.ai"]')
                        
                        print(f"[DEBUG] Total imágenes encontradas: {len(images)}")
                        
                        for i, img in enumerate(images[:4], 1):
                            try:
                                # Obtener la URL de la imagen
                                img_src = await img.get_attribute('src')
                                if img_src:
                                    print(f"[DEBUG] Imagen {i} src: {img_src[:100]}...")
                                    
                                    # Descargar imagen directamente desde la URL
                                    import requests
                                    response = requests.get(img_src)
                                    if response.status_code == 200:
                                        safe_name = f"meta_ai_image_{i}_{int(time.time())}.jpeg"
                                        save_path = self.output_dir / safe_name
                                        with open(save_path, 'wb') as f:
                                            f.write(response.content)
                                        downloaded_paths.append(str(save_path.resolve()))
                                        print(f"[DEBUG] Imagen {i} descargada a: {save_path}")
                                    else:
                                        print(f"[WARN] No se pudo descargar imagen {i} desde {img_src}")
                                else:
                                    print(f"[WARN] Imagen {i} no tiene src")
                            except Exception as e:
                                print(f"[WARN] Error descargando imagen {i}: {e}")
                        
                        # Si aún no se descargaron imágenes, intentar con los botones de descarga
                        if len(downloaded_paths) == 0:
                            buttons = await page.query_selector_all('div[aria-label="Download media"]')
                            print(f"[DEBUG] Encontrados {len(buttons)} botones de descarga")
                            
                            for i, btn in enumerate(buttons[:4], 1):
                                try:
                                    with page.expect_download() as download_info:
                                        await btn.click(timeout=5000)
                                    download = await download_info.value
                                    safe_name = f"meta_ai_image_{i}_{int(time.time())}_{await download.suggested_filename()}"
                                    save_path = self.output_dir / safe_name
                                    await download.save_as(str(save_path))
                                    downloaded_paths.append(str(save_path.resolve()))
                                    print(f"[DEBUG] Imagen {i} descargada vía botón: {save_path}")
                                except Exception as e:
                                    print(f"[WARN] Imagen {i} no descargada vía botón: {e}")

                        # --- Eliminar chat ---
                        try:
                            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                            await page.wait_for_timeout(1000)

                            menu_btn = page.locator('div[aria-label*="More options"]').last
                            if await menu_btn.is_visible():
                                await menu_btn.click(force=True)
                                await page.wait_for_timeout(1000)

                                delete_opt = page.locator('div[role="menuitem"]:has-text("Delete chat")').first
                                if not await delete_opt.is_visible():
                                    delete_opt = page.locator('text="Delete chat"').first
                                if await delete_opt.is_visible():
                                    await delete_opt.click(force=True)
                                    await page.wait_for_timeout(1000)

                                    confirm = page.locator('div[aria-label="Delete"]').first
                                    if not await confirm.is_visible():
                                        confirm = page.locator('span:text-is("Delete")').last
                                    if await confirm.is_visible():
                                        await confirm.click(force=True)
                        except Exception as e:
                            print(f"[WARN] Limpieza de chat fallida (no crítico): {e}", file=sys.stderr)

                    except PlaywrightTimeoutError:
                        print("[WARN] Timeout: no se generaron 4 imágenes a tiempo", file=sys.stderr)

                else:
                    # modo manual: solo esperar
                    await page.wait_for_timeout(timeout * 1000)

                # Cerrar el navegador al finalizar el proceso
                print("Cerrando navegador...")
                try:
                    await context.close()
                except Exception as e:
                    print(f"[WARN] Error al cerrar contexto: {e}", file=sys.stderr)

                # Convertir las imágenes descargadas a tensores de ComfyUI
                preview_images = []
                for img_path in downloaded_paths[:4]:  # Solo las primeras 4 imágenes
                    try:
                        # Cargar la imagen con PIL
                        pil_image = Image.open(img_path).convert("RGB")
                        # Convertir a tensor
                        image_tensor = torch.from_numpy(
                            (np.array(pil_image) / 255.0).astype(np.float32)
                        ).unsqueeze(0)  # Agregar dimensión batch
                        preview_images.append(image_tensor)
                    except Exception as e:
                        print(f"[WARN] Error cargando imagen {img_path}: {e}")
                
                # Concatenar todos los tensores en un solo tensor de batch
                if preview_images:
                    preview_images_tensor = torch.cat(preview_images, dim=0)
                else:
                    # Si no hay imágenes, crear un tensor vacío (por ejemplo, una imagen negra 512x512)
                    preview_images_tensor = torch.zeros((1, 512, 512, 3), dtype=torch.float32)

                return (preview_images_tensor,)

        except Exception as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            # Devolver tensor vacío en caso de error para que el nodo no falle completamente
            return (torch.zeros((1, 512, 512, 3), dtype=torch.float32),)


# Importar numpy si no está disponible
try:
    import numpy as np
except ImportError:
    import numpy as np

# Registro del nodo
NODE_CLASS_MAPPINGS = {
    "MetaAiImageGenerator": MetaAiImageGenerator
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MetaAiImageGenerator": "Meta AI Image Generator"
}