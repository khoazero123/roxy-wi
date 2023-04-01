import sys
import os
import bottle
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import api

import subprocess
import re

if os.getenv('DEBUG_ENABLE', 'false') == 'true':
    try:
        import debugpy
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", 'debugpy'])
        try:
            import debugpy
        except ImportError:
            result = subprocess.check_output([sys.executable, "-m", "pip", "show", 'debugpy']).decode(sys.stdout.encoding)
            location = re.search(r"Location: (.+)\n", result).group(1)
            sys.path.append(location)
            import debugpy

    DEBUG_HOST = os.getenv('DEBUG_HOST', '0.0.0.0')
    DEBUG_PORT = os.getenv('DEBUG_PORT', '5678')
    debugpy.listen((DEBUG_HOST, int(DEBUG_PORT)))
    if os.getenv('DEBUG_WAIT_FOR_CLIENT', 'false') == 'true':
        debugpy.wait_for_client()
    # debugpy.breakpoint()

application = bottle.default_app()