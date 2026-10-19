# Security and privacy

本專案只連線本機 ComfyUI HTTP loopback，停用 proxy 並拒絕 redirect。不接受雲端 provider 或 API key；這不是對其他程式或 ComfyUI custom nodes 的網路封鎖。

請在自己的機器上審查 custom nodes 與 workflow。不要將服務公開到網際網路來配合此工具，也不要在公開 issue／Git commit 中貼出憑證、個人 workflow、私人圖片或完整系統路徑。

發現漏洞時，請優先使用 repository 已啟用的私人漏洞回報管道；若尚未啟用，先向維護者詢問私下聯絡方式。一般問題可提供刪除個資後的版本、錯誤、節點種類與最小重現，勿公開敏感細節。
