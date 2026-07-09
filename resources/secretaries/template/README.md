# 秘书舰资源包模板

这个目录是用户自制秘书舰资源包的基础模板。复制整个 `template` 文件夹，改成自己的秘书舰名称后，再替换图片和台词即可。

## 必需文件

- `secretary.json`：秘书舰信息和台词配置。
- `avatar.png`：秘书舰头像或立绘裁剪图，建议使用透明背景 PNG。
- `README.md`：资源包说明，可保留也可改写。

## secretary.json 字段

```json
{
    "id": "template",
    "name": "模板秘书舰",
    "avatar": "avatar.png",
    "lines": {
        "idle": [],
        "target_changed": [],
        "completed": [],
        "history": [],
        "error": []
    }
}
```

## 台词场景说明

- `idle`：普通待机台词。
- `target_changed`：用户切换目标彩装数量时显示。
- `completed`：目标进度达到 100% 时显示。
- `history`：查看历史科研期时显示。
- `error`：自动化或数据更新出现异常时显示。

## 图片建议

- 文件名保持为 `avatar.png`，也可以在 JSON 中修改为其他 PNG 文件名。
- 建议尺寸不小于 256x256。
- GUI 会自动缩放，不需要手动裁剪到界面尺寸。

## 注意事项

- JSON 必须使用 UTF-8 编码。
- 台词列表中的每一项都必须是非空字符串。
- 资源包导入功能当前为 P2 占位，后续会加入实际复制和启用流程。
