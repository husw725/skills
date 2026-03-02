from PIL import Image
import numpy as np

def get_train_colors(image, x, y, size):
    incor, ocor = [], []
    fix = 3
    yfix = [(0, -1), (0, -2), (0, -3),
            (1, -1), (1, -2), (1, -3),
            (2, -1), (2, -2), (2, -3),
            (3, -1), (3, -2), (3, -3)]

    for i in range(int(size/3)):
        for a, b in yfix:
            incor.append(image.getpixel((x+i+fix, y+a)))
            ocor.append(image.getpixel((x+i+fix, y+b)))

    return incor, ocor

def generate_rgba_image(ocor, size):
    # Create a new RGBA image with the specified size
    rgba_image = Image.new("RGBA", (size, size))

    # Set the pixel values using the ocor data
    rgba_image.putdata(ocor*(int(size**2/len(ocor))))
    # rgba_image.putdata(ocor[1]*size*11)
    return rgba_image

def changeRuler(input_colors, output_colors):
    degree = 2
    input_colors = np.ravel(input_colors)
    output_colors = np.ravel(output_colors)
    coefficients = np.polyfit(input_colors, output_colors, degree)
    poly_function = np.poly1d(coefficients)
    return poly_function

def alpha_blend(image1, image2, alpha):
    if image1.size != image2.size:
        image2 = image2.resize(image1.size)  # Resize image2 to match image1's size
    blended_image = Image.blend(image1, image2, alpha)
    return blended_image

# Load the original image
image = Image.open('1.png')

# Set the coordinates and size of the square region
square_x = 77
square_y = 94
square_size = 47
epoch = 1

for i in range(epoch):
    input_colors, output_colors = get_train_colors(image, square_x, square_y, square_size)
    f = changeRuler(input_colors, output_colors)

    # Extract the square region
    square = image.crop((square_x, square_y, square_x + square_size, square_y + square_size))

    # Apply color transformation to the square region
    modified_square = square.point(f)

    output_img = generate_rgba_image(output_colors, square_size)

    modified_square = modified_square.resize(output_img.size)
    blended_image = alpha_blend(modified_square, output_img, 0.23)

    # Replace the modified square in the original image with the blended image
    image.paste(blended_image, (square_x, square_y, square_x + square_size, square_y + square_size))

# Display the result
image.show()
