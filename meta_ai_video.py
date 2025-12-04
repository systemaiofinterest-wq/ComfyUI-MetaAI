# ComfyUI_MetaAi/meta_ai_video.py
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

class MetaAiVideoGenerator:
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
                "iterations": ("INT", {"default": 1, "min": 1, "max": 5}),
                "profile_name": ("STRING", {"default": "meta_playwright_profile3"}),
                "namevideo": ("STRING", {"default": ""}),
                "force_generation": ("BOOLEAN", {"default": False}),  # Para forzar generación
            }
        }

    RETURN_TYPES = ("VIDEO", "IMAGE")
    RETURN_NAMES = ("video_path", "final_frame")
    FUNCTION = "generate_video"
    CATEGORY = "MetaAI"

    async def generate_video(self, image, prompt, iterations, profile_name, namevideo, force_generation):
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
            # Tomamos la primera imagen si hay batch
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
            return (None, None)

        # Procesar el prompt
        prompt_lines = [line.strip() for line in prompt.strip().split("\n") if line.strip()]
        if not prompt_lines:
            print("[ERROR] Prompt vacío.", file=sys.stderr)
            return (None, None)

        # Ajustar el número de prompts según las iteraciones
        if len(prompt_lines) < iterations:
            prompt_list = prompt_lines + [prompt_lines[-1]] * (iterations - len(prompt_lines))
        else:
            prompt_list = prompt_lines[:iterations]

        all_video_paths = []
        final_frame_path = None

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

                for i in range(iterations):
                    current_prompt = prompt_list[i]

                    if i == 0:
                        await page.goto("https://www.meta.ai/media  ", timeout=60000)
                        try:
                            await page.wait_for_selector('text="Image"', timeout=30000)
                            await page.click('text="Image"')
                            await asyncio.sleep(1)
                            await page.wait_for_selector('text="Video"', timeout=15000)
                            await page.click('text="Video"')
                            await asyncio.sleep(1)
                        except Exception as e:
                            print(f"[WARN] Navegación inicial inestable: {e}", file=sys.stderr)

                    # Subir imagen
                    try:
                        await page.wait_for_selector('text="Upload image"', timeout=15000)
                        async with page.expect_file_chooser() as fc_info:
                            await page.click('text="Upload image"')
                        file_chooser = await fc_info.value
                        await file_chooser.set_files(current_input_path)
                        await asyncio.sleep(2)
                    except Exception:
                        # Intento fallback
                        try:
                            await page.set_input_files('input[type="file"]', current_input_path)
                        except Exception as e:
                            raise RuntimeError(f"Falló subida de imagen: {e}")

                    # Prompt
                    prompt_container_selector = 'div[contenteditable="true"][role="textbox"]'
                    await page.wait_for_selector(prompt_container_selector, timeout=15000)
                    await page.click(prompt_container_selector)
                    await page.keyboard.press("Control+a")
                    await page.keyboard.press("Delete")
                    await asyncio.sleep(0.3)
                    await page.fill(prompt_container_selector, current_prompt)
                    await asyncio.sleep(0.5)

                    # Botón Animate
                    animar_selector = 'div[role="button"]:has-text("Animate")'
                    clicked = False
                    for _ in range(180):  # ~90s
                        btn = await page.query_selector(animar_selector)
                        if btn:
                            tabindex = await btn.get_attribute("tabindex")
                            aria_disabled = await btn.get_attribute("aria-disabled")
                            if tabindex == "0" and aria_disabled != "true":
                                await btn.click()
                                clicked = True
                                break
                        await asyncio.sleep(0.5)

                    if not clicked:
                        raise TimeoutError("Botón 'Animate' no se activó")

                    # Esperar video
                    video_url = await self.wait_for_video_after_overlay_disappears(page, max_wait=150)

                    base_name = self.get_next_meta_name()
                    video_path = self.output_dir / f"{base_name}.mp4"
                    frame_path = self.output_dir / f"{base_name}.png"

                    response = requests.get(
                        video_url,
                        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                        stream=True,
                        timeout=30
                    )
                    response.raise_for_status()
                    with open(video_path, "wb") as f:
                        for chunk in response.iter_content(8192):
                            f.write(chunk)

                    self.extract_last_frame(str(video_path), str(frame_path))
                    all_video_paths.append(str(video_path))

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
                            
                        except Exception as e:
                            print(f"[WARN] Error en el proceso de eliminación de chat #{attempts + 1}: {e}", file=sys.stderr)
                            attempts += 1
                            continue
                    
                    if attempts >= max_attempts:
                        print(f"[WARN] Se alcanzó el límite de intentos ({max_attempts}) para eliminar chats.")

                    if temp_input.exists():
                        try:
                            temp_input.unlink()
                        except:
                            pass

                    if i < iterations - 1:
                        current_input_path = str(frame_path)
                        temp_input = Path(frame_path)
                    else:
                        final_frame_path = str(frame_path)

                    await asyncio.sleep(2)

                # Cerrar el navegador
                await context.close()

            # Renombrar/concatenar videos
            if all_video_paths:
                if len(all_video_paths) == 1:
                    original_path = Path(all_video_paths[0])
                    if namevideo:
                        final_video_path = self.output_dir / f"{namevideo}.mp4"
                        if final_video_path.exists():
                            final_video_path.unlink()
                        original_path.rename(final_video_path)
                    else:
                        final_video_path = original_path
                else:
                    if namevideo:
                        final_video_path = self.output_dir / f"{namevideo}.mp4"
                    else:
                        combined_name = self.get_next_meta_name()
                        final_video_path = self.output_dir / f"{combined_name}_chain.mp4"
                    if final_video_path.exists():
                        final_video_path.unlink()
                    self.concatenate_videos(all_video_paths, final_video_path)
            else:
                final_video_path = self.output_dir / "empty.mp4"
                final_video_path.touch()

            # Convertir la imagen final a tensor de ComfyUI
            if final_frame_path:
                try:
                    pil_final = Image.open(final_frame_path).convert("RGB")
                    np_final = np.array(pil_final).astype(np.float32) / 255.0
                    final_frame_tensor = torch.from_numpy(np_final).unsqueeze(0)  # Agregar dimensión batch
                except Exception as e:
                    print(f"[WARN] Error cargando imagen final: {e}")
                    final_frame_tensor = torch.zeros((1, 512, 512, 3), dtype=torch.float32)
            else:
                final_frame_tensor = torch.zeros((1, 512, 512, 3), dtype=torch.float32)

            # Devolver el path del video y el tensor de la imagen final
            return (str(final_video_path.resolve()).replace("\\", "/"), final_frame_tensor)

        except Exception as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            return (None, torch.zeros((1, 512, 512, 3), dtype=torch.float32))

    def get_next_meta_name(self) -> str:
        existing = glob.glob(str(self.output_dir / "meta_*.mp4"))
        numbers = []
        for f in existing:
            match = re.search(r"meta_(\d+)", Path(f).stem)
            if match:
                numbers.append(int(match.group(1)))
        next_num = max(numbers) + 1 if numbers else 1
        return f"meta_{next_num:03d}"

    def extract_last_frame(self, video_path: str, output_image_path: str):
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise IOError(f"No se pudo abrir el video: {video_path}")
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            cap.release()
            raise ValueError("Video sin frames.")
        cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames - 1)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            raise RuntimeError("No se pudo leer el último frame.")
        cv2.imwrite(output_image_path, frame, [cv2.IMWRITE_PNG_COMPRESSION, 0])

    def concatenate_videos(self, video_paths, output_path):
        if not video_paths:
            raise ValueError("No hay videos para concatenar.")
        cap = cv2.VideoCapture(video_paths[0])
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

        for vid_path in video_paths:
            cap = cv2.VideoCapture(vid_path)
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                out.write(frame)
            cap.release()
        out.release()

    async def wait_for_video_after_overlay_disappears(self, page, max_wait=150):
        overlay_selector = 'div[style*="--x-backdropFilter: blur"]'

        try:
            await page.wait_for_selector(overlay_selector, state="attached", timeout=15000)
        except:
            pass

        try:
            await page.wait_for_selector(overlay_selector, state="detached", timeout=max_wait * 1000)
        except:
            pass

        for _ in range(max_wait):
            video_elements = await page.query_selector_all("video")
            for video in video_elements:
                try:
                    src = await video.get_attribute("src")
                    if src and isinstance(src, str) and src.strip().startswith("http") and "blob:" not in src:
                        return src
                except:
                    pass
            await asyncio.sleep(1)

        raise RuntimeError("No se encontró URL de video descargable.")


# Importar torch si no está disponible
try:
    import torch
except ImportError:
    import torch

# Registro del nodo
NODE_CLASS_MAPPINGS = {
    "MetaAiVideoGenerator": MetaAiVideoGenerator
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MetaAiVideoGenerator": "Meta AI Video Generator"
}