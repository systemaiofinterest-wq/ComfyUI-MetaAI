# ComfyUI_MetaAi/__init__.py
from .meta_ai_t2i_nodes import NODE_CLASS_MAPPINGS as t2i_mappings, NODE_DISPLAY_NAME_MAPPINGS as t2i_display_mappings
from .meta_ai_open import MetaAiBrowserNode
from .meta_ai_i2v_single import MetaAiSingleVideoGenerator

# Combinar los mappings
NODE_CLASS_MAPPINGS = {
    **t2i_mappings,
    "MetaAiBrowserNode": MetaAiBrowserNode,
    "MetaAiSingleVideoGenerator": MetaAiSingleVideoGenerator,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    **t2i_display_mappings,
    "MetaAiBrowserNode": "Meta AI Browser Launcher",
    "MetaAiSingleVideoGenerator": "Meta AI Single Video Generator"
}


__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']