# 应用图标说明

请将应用图标文件放置在此目录下：

## 需要的图标文件

1. **icon.png** - 主图标文件
   - 建议尺寸: 512x512 或更大
   - 格式: PNG
   - 用途: Linux应用图标

## 如何生成图标

如果您没有图标文件，可以使用以下方法：

### 方法1: 使用在线工具
访问 https://www.favicon-generator.org/ 上传您的图片生成各种尺寸的图标

### 方法2: 使用命令行工具
```bash
# 安装 ImageMagick
sudo apt-get install imagemagick

# 将图片转换为所需尺寸
convert input.png -resize 512x512 icon.png
```

### 方法3: 使用占位图标
如果暂时没有图标，可以使用纯色背景作为占位：

```bash
# 创建一个简单的蓝色方块作为占位图标
convert -size 512x512 xc:#1976D2 icon.png
```

## 当前状态
⚠️ 请在打包前添加实际的应用图标文件
