# 測試圖片與跑步範例 / Sample assets

這三個檔案由本儲存庫維護者提供，供安裝後試跑與查看輸出效果：

| 檔案 | 說明 |
|---|---|
| [sample-character.png](sample-character.png) | 1536×1536 的角色原圖，含綠色背景；不是已去背的透明成品。 |
| [sample-character-run-spritesheet.png](sample-character-run-spritesheet.png) | 1024×128 的透明PNG圖集，由左至右8格，每格128×128。 |
| [sample-character-run-preview.gif](sample-character-run-preview.gif) | 128×128、8格的透明跑步預覽，整個循環1秒。 |

遊戲內以8fps播放PNG圖格：每格125ms。GIF受格式精度限制，使用120/130ms交替，總長仍為1秒。重新生成的動作可能不同，附帶成品是參考結果，不是每次輸出的保證。

原圖雖然有Alpha通道，背景實際上仍近乎不透明。請先去除綠底，確認準備好的生成輸入沒有殘留綠色方框，再提交ComfyUI。

## 素材來源與使用

來源：由本儲存庫維護者 yuwechang 提供。**本目錄的角色原圖、PNG圖集與GIF動畫也採用MIT授權**，與專案原始碼相同；完整條款見 [LICENSE](LICENSE)。

These assets were supplied by repository maintainer yuwechang and are licensed under the MIT License, including the source character image, PNG sprite sheet and GIF animation. See [LICENSE](LICENSE). The source image has a green background. The sprite sheet contains eight transparent 128×128 frames; play at 8 fps for a one-second loop. The GIF uses alternating 120/130 ms delays. Generated motion may differ from the included example.
