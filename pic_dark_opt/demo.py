from PIL import Image,ImageFilter
import numpy as np
import time

def get_train_colors(image, x, y, size):
    incor,ocor = [],[]
    fix = 1
    yfix = [(0,-1),(0,-2),(0,-3),
            (1,-1),(1,-2),(1,-3),
            (2,-1),(2,-2),(2,-3),
            (3,-1),(3,-2),(3,-3),
            ]
    for i in range(int(size/3)):
        for a,b in yfix:
            incor.append(image.getpixel((x+i+fix,y+a)))
            ocor.append(image.getpixel((x+i+fix,y+b)))

            # incor.append(image.getpixel((x+size-i-fix,y+a)))
            # ocor.append(image.getpixel((x+size-i-fix,y+b)))


    return incor,ocor

def changeRuler(input_colors, output_colors):
    degree = 2
    input_colors = np.ravel(input_colors)
    output_colors = np.ravel(output_colors)
    coefficients = np.polyfit(input_colors, output_colors, degree)
    poly_function = np.poly1d(coefficients)
    return poly_function

# 加载原始图像
image = Image.open('1.png')

# 设置正方形区域的左上角坐标和边长
square_x = 77
square_y = 94
square_size = 47
epoch = 2
start = time.time()
for i in range(epoch):
    input_colors, output_colors = get_train_colors(image, square_x, square_y, square_size)

    f = changeRuler(input_colors, output_colors)

    # 提取正方形区域
    square = image.crop((square_x, square_y, square_x + square_size, square_y + square_size))

    # 将颜色变换应用于正方形区域
    modified_square = square.point(f)

    # 在原始图片中替换修改后的正方形区域
    image.paste(modified_square, (square_x, square_y, square_x + square_size, square_y + square_size))

    # image.show()
    image_array = np.array(image)
    for i in range(20):
        # 使用平均值滤波器进行图像模糊
        blurred_array = np.array(image.filter(ImageFilter.GaussianBlur if i&1==1 else ImageFilter.BLUR))
        # 修复拼接痕迹
        image_array = np.where(image_array < 180, image_array, blurred_array)
    # 转换回PIL图像
    image = Image.fromarray(image_array.astype(np.uint8))
    
# 显示结果
image.show()
image.save("output.png")

print(time.time() - start)
