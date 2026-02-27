import os
import sys
import time
import glob
import cv2
import re
import numpy as np
from pathlib import Path
from PIL import Image
import requests
import asyncio
import traceback
import json

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

class MetaAiSingleVideoGenerator:
    def __init__(self):
        # Directorio de salida en la carpeta principal de ComfyUI
        self.output_dir = Path(__file__).parent.parent.parent / "output" / "meta_ai"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),  # Entrada de imagen de ComfyUI
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "profile_name": ("STRING", {"default": "meta_playwright_profile3"}),
                "namevideo": ("STRING", {"default": ""}),
                "force_generation": ("BOOLEAN", {"default": False}),  # Para forzar generación
            }
        }

    # --- NUEVO MÉTODO AÑADIDO ---
    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # Al devolver NaN, ComfyUI asume que las entradas siempre han cambiado
        # y forzará la ejecución del nodo cada vez que le des a "Queue Prompt".
        return float("NaN")
    # ----------------------------

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video_path",)
    FUNCTION = "generate_video"
    CATEGORY = "MetaAI"

    async def generate_video(self, image, prompt, profile_name, namevideo, force_generation):
        """
        Genera un video usando Meta AI a partir de una imagen y un prompt.
        """
        # Aseguramos que el nombre del perfil no esté vacío
        profile_name = profile_name.strip() or "meta_playwright_profile3"
        
        # Directorio fijo para el perfil (dentro del directorio del nodo)
        user_data_dir = Path(__file__).parent / profile_name
        user_data_dir.mkdir(parents=True, exist_ok=True)

        # Convertir el tensor de imagen de ComfyUI a PIL Image
        try:
            # El tensor tiene forma (batch, height, width, channels)
            if len(image.shape) == 4:
                img_tensor = image[0]  # Tomar la primera imagen del batch
            else:
                img_tensor = image
            
            # Convertir de tensor a numpy array y luego a PIL Image
            np_img = (img_tensor.cpu().numpy() * 255).astype(np.uint8)
            pil_img = Image.fromarray(np_img, mode="RGB")
            
            # Guardar temporalmente como PNG
            temp_input = self.output_dir / f"input_{int(time.time() * 1000)}.png"
            pil_img.save(temp_input, "PNG")
            current_input_path = str(temp_input)
            
        except Exception as e:
            print(f"[ERROR] Error al convertir la imagen: {e}", file=sys.stderr)
            return (None,)

        # Procesar el prompt
        prompt_lines = [line.strip() for line in prompt.strip().split("\n") if line.strip()]
        if not prompt_lines:
            print("[ERROR] Prompt vacío.", file=sys.stderr)
            return (None,)

        # Tomar solo el primer prompt
        current_prompt = prompt_lines[0]
        video_path_final = None

        try:
            async with async_playwright() as p:
                context = await p.chromium.launch_persistent_context(
                    str(user_data_dir),
                    headless=False,
                    locale="en-US",
                    permissions=["clipboard-read", "clipboard-write"],
                    args=[
                        "--start-maximized",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-features=TranslateUI,msUnifiedAppUIToolbar",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-infobars",
                        "--lang=en-US"
                    ],
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                    accept_downloads=True,
                    ignore_default_args=["--enable-automation"],
                    timeout=30000
                )

                page = context.pages[0] if context.pages else await context.new_page()

                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    Object.defineProperty(document, 'hidden', { value: false });
                    Object.defineProperty(document, 'visibilityState', { value: 'visible' });
                    document.dispatchEvent(new Event('visibilitychange'));
                """)

                print("[INFO] Cargando Meta AI...")
                await page.goto("https://www.meta.ai/media", timeout=60000)
                await page.wait_for_load_state("networkidle")

                # --- 1. CAMBIAR A MODO VIDEO ---
                try:
                    print("[INFO] Verificando modo Video...")
                    await asyncio.sleep(2)
                    mode_trigger = page.locator('button, [role="button"]').filter(has_text="Image").first
                    if await mode_trigger.is_visible():
                        await mode_trigger.click()
                        await asyncio.sleep(1)
                        video_option = page.get_by_text("Video", exact=True).locator("visible=true").last
                        await video_option.click()
                        print("[INFO] Modo 'Video' seleccionado con éxito.")
                    else:
                        print("[INFO] El modo 'Video' ya parece estar activo.")
                except Exception as e:
                    print(f"[WARN] No se pudo cambiar el modo manualmente: {e}", file=sys.stderr)

                # --- 2. SUBIR IMAGEN ---
                try:
                    print(f"[INFO] Intentando subir imagen: {current_input_path}")
                    attach_btn = page.locator('button[data-testid="composer-add-attachment-button"]')
                    if await attach_btn.count() > 0:
                        async with page.expect_file_chooser() as fc_info:
                            await attach_btn.first.click()
                        file_chooser = await fc_info.value
                        await file_chooser.set_files(current_input_path)
                        
                        # Esperar a que la imagen cargue (desaparición de clase opacity-70)
                        print("[INFO] Esperando procesamiento de imagen...")
                        await page.locator('img[src^="blob:"]:not(.opacity-70)').first.wait_for(state="visible", timeout=30000)
                        print("[INFO] Imagen cargada correctamente.")
                        await asyncio.sleep(2)
                    else:
                        print("[ERROR] No se encontró el botón de adjuntar archivo.")
                except Exception as e:
                    print(f"[ERROR] Error durante la subida de imagen: {e}", file=sys.stderr)

                # --- 3. INGRESAR PROMPT Y GENERAR ---
                video_selector = 'div[data-testid="generated-video"]'
                initial_video_count = await page.locator(video_selector).count()
                print(f"[INFO] Videos detectados antes de generar: {initial_video_count}")

                prompt_locator = page.locator('div[contenteditable="true"][role="textbox"]')
                await prompt_locator.wait_for(state="visible")
                await prompt_locator.click()
                
                # Usar el portapapeles para insertar el texto y evitar bloqueos
                await page.evaluate("async (text) => { await navigator.clipboard.writeText(text); }", current_prompt)
                await page.keyboard.press("Control+V")
                await asyncio.sleep(1)
                await page.keyboard.press("Enter")
                print("[INFO] Prompt enviado. Generando video...")

                # --- 4. BUCLE DE ESPERA PARA LA GENERACIÓN ---
                start_time = time.time()
                wait_timeout = 240  # 4 minutos máximo
                new_video_found = False
                
                while time.time() - start_time < wait_timeout:
                    current_count = await page.locator(video_selector).count()
                    if current_count > initial_video_count:
                        new_video_found = True
                        print(f"[INFO] ¡Nuevo video generado detectado! (Total: {current_count})")
                        break
                    await asyncio.sleep(4)

                # --- 5. IDENTIFICAR Y DESCARGAR EL ÚLTIMO VIDEO ---
                if new_video_found:
                    print("[INFO] Esperando a que el video esté listo para descarga...")
                    await asyncio.sleep(10)  # Tiempo de gracia
                    
                    all_videos = await page.locator(video_selector).all()
                    
                    if all_videos:
                        target_video_locator = all_videos[0]
                        print("[INFO] Seleccionando el primer video de la lista (índice 0)...")
                        
                        try:
                            video_url = await target_video_locator.get_attribute("data-video-url")
                            if not video_url:
                                video_tag = target_video_locator.locator("video").first
                                video_url = await video_tag.get_attribute("src")

                            if video_url:
                                print(f"[INFO] Iniciando descarga...")
                                response = await page.request.get(video_url, timeout=60000)
                                if response.status == 200:
                                    base_name = namevideo if namevideo else self.get_next_meta_name()
                                    video_path = self.output_dir / f"{base_name}.mp4"
                                    
                                    body = await response.body()
                                    with open(video_path, "wb") as f:
                                        f.write(body)
                                        
                                    video_path_final = str(video_path.resolve()).replace("\\", "/")
                                    print(f"[SUCCESS] ¡Video guardado con éxito! -> {video_path_final}")
                                else:
                                    print(f"[ERROR] HTTP {response.status} al intentar descargar el archivo.")
                            else:
                                print("[ERROR] No se pudo localizar la URL de descarga.")
                        except Exception as e:
                            print(f"[ERROR] Error durante la descarga: {e}", file=sys.stderr)
                    else:
                        print("[ERROR] No se encontraron elementos de video tras la generación.")
                else:
                    print("[ERROR] El tiempo de espera terminó sin detectar un video nuevo.")

                # --- 6. LIMPIEZA DE HISTORIAL (Eliminando solo el actual para evitar bucles colgados) ---
                print("[INFO] Limpiando historial del chat...")
                try:
                    dots_menu = page.locator('button:has(svg path[d*="M8 14.125"])').first
                    if await dots_menu.is_visible():
                        await dots_menu.click()
                        await asyncio.sleep(1)
                        await page.get_by_text("Delete", exact=True).first.click()
                        await asyncio.sleep(1)
                        await page.get_by_role("button", name="Delete").click()
                        print("[INFO] Historial eliminado.")
                        await asyncio.sleep(2)
                except Exception as e:
                    print(f"[WARN] No se pudo realizar la limpieza del historial: {e}", file=sys.stderr)

                await context.close()

                if video_path_final:
                    return (video_path_final,)
                else:
                    return (None,)

        except Exception as e:
            print(f"[ERROR CRÍTICO] {e}", file=sys.stderr)
            traceback.print_exc()
            return (None,)

    def get_next_meta_name(self) -> str:
        existing = glob.glob(str(self.output_dir / "meta_*.mp4"))
        numbers = []
        for f in existing:
            match = re.search(r"meta_(\d+)", Path(f).stem)
            if match:
                numbers.append(int(match.group(1)))
        next_num = max(numbers) + 1 if numbers else 1
        return f"meta_{next_num:03d}"

# Importar torch si no está disponible
try:
    import torch
except ImportError:
    import torch

# Registro del nodo
NODE_CLASS_MAPPINGS = {
    "MetaAiSingleVideoGenerator": MetaAiSingleVideoGenerator
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MetaAiSingleVideoGenerator": "Meta AI Single Video Generator"
}
