import os
import sys
import time
import json
import re
import asyncio
from pathlib import Path
import torch
import numpy as np
from PIL import Image
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

class MetaAiImageGenerator:
    def __init__(self):
        # Diretório de saída na pasta principal do ComfyUI
        self.output_dir = Path(__file__).parent.parent.parent / "output" / "meta_ai_image"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "timeout": ("INT", {"default": 60, "min": 10, "max": 300}),
                "aspect_ratio": (["1:1", "16:9", "9:16"], {"default": "1:1"}),
            },
            "optional": {
                "profile_name": ("STRING", {"default": "meta_playwright_profile"}),
            }
        }

    # --- NUEVO MÉTODO AÑADIDO ---
    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # Al devolver NaN, ComfyUI asume que las entradas siempre han cambiado
        # y forzará la ejecución del nodo cada vez que le des a "Queue Prompt".
        return float("NaN")
    # ----------------------------

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("preview_images",)
    FUNCTION = "generate_images"
    CATEGORY = "MetaAI"

    async def generate_images(self, prompt, timeout, aspect_ratio, profile_name="meta_playwright_profile"):
        # Garante que o nome do perfil seja válido
        profile_name = profile_name.strip() or "meta_playwright_profile"
        user_data_dir = Path(__file__).parent / profile_name
        user_data_dir.mkdir(parents=True, exist_ok=True)

        downloaded_paths = []

        async with async_playwright() as p:
            # Lançar contexto com permissões de área de transferência (necessário para a nova lógica)
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
            
            print(f"[MetaAI] A carregar interface com o perfil: {profile_name}...")
            await page.goto("https://www.meta.ai/media", timeout=60000)
            await page.wait_for_load_state("domcontentloaded")

            # --- LÓGICA DE SELECÇÃO DE ASPECT RATIO ---
            try:
                print(f"[MetaAI] A configurar Aspect Ratio: {aspect_ratio}")
                await asyncio.sleep(2)
                aspect_ratio_pattern = re.compile(r"^(9:16|1:1|16:9)$")
                menu_locator = page.locator('span[data-slot="select-value"]').filter(has_text=aspect_ratio_pattern)

                if await menu_locator.count() > 0:
                    await menu_locator.first.wait_for(state="visible", timeout=10000)
                    current_value = (await menu_locator.first.inner_text()).strip()
                    
                    if current_value != aspect_ratio:
                        await menu_locator.first.click()
                        await asyncio.sleep(1)
                        option_to_click = page.get_by_text(aspect_ratio, exact=True).locator("visible=true")
                        if await option_to_click.count() > 0:
                            await option_to_click.last.click()
                            await asyncio.sleep(1)
                else:
                    print("[MetaAI] Botão de Aspect Ratio não detectado, será usado o padrão.")
            except Exception as e:
                print(f"[MetaAI] Erro no Aspect Ratio: {e}")

            # --- LÓGICA DE INSERÇÃO DE PROMPT (COLAR TEXTO) ---
            try:
                prompt_locator = page.locator('div[contenteditable="true"][role="textbox"][data-testid="composer-input"]')
                await prompt_locator.wait_for(state="visible", timeout=10000)
                await prompt_locator.click()
                await asyncio.sleep(0.5)

                # Contar imagens prévias
                initial_image_count = await page.locator('img[data-testid="generated-image"]').count()
                
                # Colar via área de transferência
                await page.evaluate("async (text) => { await navigator.clipboard.writeText(text); }", prompt)
                await page.keyboard.press("Control+V")
                await asyncio.sleep(0.5)
                await page.keyboard.press("Enter")

                # --- ESPERA DE GERAÇÃO ---
                print(f"[MetaAI] A aguardar a geração das imagens...")
                start_time = time.time()
                new_images_detected = False
                
                while time.time() - start_time < timeout:
                    current_count = await page.locator('img[data-testid="generated-image"]').count()
                    if current_count >= initial_image_count + 4:
                        new_images_detected = True
                        break
                    await asyncio.sleep(1)

                if new_images_detected:
                    await asyncio.sleep(2) # Margem para carregamento de URLs
                    all_images_locators = await page.locator('img[data-testid="generated-image"]').all()
                    target_images = all_images_locators[:4]

                    for idx, img_locator in enumerate(target_images):
                        src_url = await img_locator.get_attribute("src")
                        if src_url:
                            response = await page.request.get(src_url)
                            if response.status == 200:
                                filename = f"meta_ai_{int(time.time())}_{idx+1}.jpg"
                                file_path = self.output_dir / filename
                                file_path.write_bytes(await response.body())
                                downloaded_paths.append(str(file_path.resolve()))
                else:
                    print("[MetaAI] Não foram detectadas novas imagens no tempo previsto.")

                # --- APAGAR HISTÓRICO (LIMPEZA) ---
                try:
                    svg_path = "M8 14.125a1.875 1.875 0 1 1 0 3.75 1.875 1.875 0 0 1 0-3.75zm8 0a1.875 1.875 0 1 1 0 3.75 1.875 1.875 0 0 1 0-3.75zm8 0a1.875 1.875 0 1 1 0 3.75 1.875 1.875 0 0 1 0-3.75z"
                    menu_button = page.locator(f'button:has(svg path[d="{svg_path}"])').first
                    if await menu_button.is_visible():
                        await menu_button.click()
                        await asyncio.sleep(1)
                        delete_option = page.get_by_text("Delete", exact=True)
                        if await delete_option.is_visible():
                            await delete_option.click()
                            await asyncio.sleep(1)
                            confirm_button = page.get_by_role("button", name="Delete")
                            if await confirm_button.is_visible():
                                await confirm_button.click()
                except Exception as e:
                    print(f"[MetaAI] Erro na limpeza opcional: {e}")

            except Exception as e:
                print(f"[MetaAI] Erro durante a geração: {e}")

            await context.close()

        # --- PROCESSAMENTO DE TENSORES ---
        preview_images = []
        for img_path in downloaded_paths:
            try:
                pil_image = Image.open(img_path).convert("RGB")
                image_tensor = torch.from_numpy(
                    (np.array(pil_image) / 255.0).astype(np.float32)
                ).unsqueeze(0)
                preview_images.append(image_tensor)
            except Exception as e:
                print(f"[MetaAI] Erro ao carregar {img_path}: {e}")

        if preview_images:
            return (torch.cat(preview_images, dim=0),)
        else:
            return (torch.zeros((1, 512, 512, 3), dtype=torch.float32),)

# Registo do nó
NODE_CLASS_MAPPINGS = {
    "MetaAiImageGenerator": MetaAiImageGenerator
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MetaAiImageGenerator": "Meta AI Image Generator"
}
