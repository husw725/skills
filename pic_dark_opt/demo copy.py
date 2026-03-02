from PIL import Image,ImageEnhance
import numpy as np

def get_train_colors(image, x, y, size):
    incor,ocor = [],[]
    fix = 3
    for i in range(int(size/3)):
        incor.append(image.getpixel((x+i+fix,y)))
        ocor.append(image.getpixel((x+i+fix,y-1)))
        incor.append(image.getpixel((x+size-i-fix,y)))
        ocor.append(image.getpixel((x+size-i-fix,y-1)))
    return incor,ocor

def changeRuler(input_colors, output_colors):
    degree = 2
    input_colors = np.array(input_colors)
    output_colors = np.array(output_colors)

    # 提取颜色的亮度和饱和度
    input_luminance = np.mean(input_colors, axis=1)
    output_luminance = np.mean(output_colors, axis=1)
    input_saturation = np.std(input_colors, axis=1)
    output_saturation = np.std(output_colors, axis=1)

    # 将颜色的亮度和饱和度与RGB值拼接
    input_colors_extended = np.column_stack((input_colors, input_luminance, input_saturation))
    output_colors_extended = np.column_stack((output_colors, output_luminance, output_saturation))

    # 使用多项式拟合
    coefficients = np.polyfit(input_colors_extended.flatten(), output_colors_extended.flatten(), degree)
    poly_function = np.poly1d(coefficients)
    return poly_function

# 加载原始图像
image = Image.open('1.png')

# 设置正方形区域的左上角坐标和边长
square_x = 77
square_y = 94
square_size = 47
epoch = 1
for i in range(epoch):
    input_colors, output_colors = get_train_colors(image, square_x, square_y, square_size)

    f = changeRuler(input_colors, output_colors)

    # 提取正方形区域
    square = image.crop((square_x, square_y, square_x + square_size, square_y + square_size))

    # 将颜色变换应用于正方形区域
    modified_square = square.point(f)
    # enhancer = ImageEnhance.Brightness(square)

    # 在原始图片中替换修改后的正方形区域
    image.paste(modified_square, (square_x, square_y, square_x + square_size, square_y + square_size))

# 显示结果
image.show()
