name: Render video

on:
  repository_dispatch:
    types: [render_video]

permissions:
  contents: write

jobs:
  render:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repo (para traer render.py)
        uses: actions/checkout@v4

      - name: Instalar ffmpeg y librerias de Python
        run: |
          sudo apt-get update && sudo apt-get install -y ffmpeg fonts-dejavu
          pip install edge-tts Pillow requests

      - name: Generar video completo (escenas, movimiento, subtitulos)
        env:
          RENDER_TEXT: ${{ github.event.client_payload.text }}
        run: python3 render.py

      - name: Publicar el video y la miniatura como Release
        uses: softprops/action-gh-release@v2
        with:
          tag_name: video-${{ github.run_id }}
          files: |
            video.mp4
            thumbnail.jpg

      - name: Avisar a Make que el video ya esta listo
        run: |
          TITLE=$(cat title.txt)
          python3 -c "
          import json, subprocess
          payload = {
              'video_url': 'https://github.com/${{ github.repository }}/releases/download/video-${{ github.run_id }}/video.mp4',
              'thumbnail_url': 'https://github.com/${{ github.repository }}/releases/download/video-${{ github.run_id }}/thumbnail.jpg',
              'title': '''$TITLE'''
          }
          subprocess.run(['curl', '-X', 'POST', '${{ github.event.client_payload.callback_url }}',
                           '-H', 'Content-Type: application/json',
                           '-d', json.dumps(payload)])
          "
