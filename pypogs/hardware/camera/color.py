__all__ = ['debayer_image']

import numpy as np

def debayer_image(img, order='RGGB', downsize=False):
    """Debayer image (2d np array) with given pixel order.
    Order can be RGGB (default), BGGR, GBRG, or GRBG.
    If downsize is set to True, the output image will be half the size of the
    original.
    """

    (height, width) = img.shape
    datatype = img.dtype
    # Unpack pixels. Determine the pixel offset (position in each quad group)
    offset = {}
    green2 = False
    for c, offs in zip(order.upper(), [(0, 0), (0, 1), (1, 0), (1, 1)]):
        if c == 'G':
            if not green2:
                offset['G1'] = offs
                green2 = True
            else:
                offset['G2'] = offs
        else:
            offset[c] = offs

    # Unpack channels to individual arrays
    img_red     = img[offset['R' ][0]::2, offset['R' ][1]::2]
    img_green_1 = img[offset['G1'][0]::2, offset['G1'][1]::2]
    img_green_2 = img[offset['G2'][0]::2, offset['G2'][1]::2]
    img_blue    = img[offset['B' ][0]::2, offset['B' ][1]::2]

    if downsize:
        # Use red and blue as is, average green. Gives half outsize.
        out = np.zeros((height//2, width//2, 3), dtype=datatype)
        # Red green and blue channels. Green has a thrid dim for the two pixels
        # in each group.
        out[:, :, 0] = img_red
        out[:, :, 1] = ((img_green_1.astype(np.float32) +
                         img_green_2.astype(np.float32))/2).astype(datatype)
        out[:, :, 2] = img_blue

    else:
        # Bilinear interpolation to give approximate full outsize.
        out = np.zeros((height, width, 3), dtype=datatype)

        # Debayer/interpolate red and blue channels
        out[:, :, 0] = insert_red_blue(offset['R'][0], offset['R'][1], img_red).astype(datatype)
        out[:, :, 2] = insert_red_blue(offset['B'][0], offset['B'][1], img_blue).astype(datatype)

        # Debayer/interpolate green channel
        out[:, :, 1] = insert_green(offset['G1'][0], offset['G1'][1], img_green_1,
                                    offset['G2'][0], offset['G2'][1], img_green_2,).astype(datatype)

    return out


def insert_red_blue(oy, ox, image):
    out = np.zeros(np.array(image.shape)*2, dtype=np.float32)
    # Pad array to deal with edges
    image = np.pad(image, 1, mode='edge').astype(np.float32)
    # Set output array according to bilinear interpolation
    out[oy::2, ox::2] = image[1:-1, 1:-1]
    out[(oy+1)%2::2, ox::2] = (image[(oy+1)%2  : (oy+1)%2-2,          1:-1]
                             + image[(oy+1)%2+1:((oy+1)%2-1 or None), 1:-1])/2
    out[oy::2, (ox+1)%2::2] = (image[1:-1, (ox+1)%2  :(ox+1)%2-2]
                             + image[1:-1, (ox+1)%2+1:((ox+1)%2-1 or None)])/2
    out[(oy+1)%2::2, (ox+1)%2::2] = (image[(oy+1)%2  : (oy+1)%2-2,           (ox+1)%2+1:((ox+1)%2-1 or None)]
                                   + image[(oy+1)%2+1:((oy+1)%2-1 or None):, (ox+1)%2+1:((ox+1)%2-1 or None)]
                                   + image[(oy+1)%2  : (oy+1)%2-2,           (ox+1)%2  :(ox+1)%2-2]
                                   + image[(oy+1)%2+1:((oy+1)%2-1 or None),  (ox+1)%2  :(ox+1)%2-2])/4
    return out

def insert_green(oy1, ox1, image1, oy2, ox2, image2):
    out = np.zeros(np.array(image1.shape)*2, dtype=np.float32)
    # Pad arrays to deal with edges
    image1 = np.pad(image1, 1, mode='edge').astype(np.float32)
    image2 = np.pad(image2, 1, mode='edge').astype(np.float32)
    out[oy1::2, ox1::2] = image1[1:-1, 1:-1]
    out[(oy1+1)%2::2, (ox1+1)%2::2] = image2[1:-1, 1:-1]
    out[(oy1+1)%2::2, ox1::2] = (image1[(oy1+1)%2:(oy1+1)%2-2, 1:-1]
                               + image1[(oy1+1)%2+1:((oy1+1)%2-1 or None), 1:-1]
                               + image2[1:-1, (ox2+1)%2+1:((ox2+1)%2-1 or None)]
                               + image2[1:-1, (ox2+1)%2:(ox2+1)%2-2])/4

    out[oy1::2, (ox1+1)%2::2] = (image1[1:-1, (ox1+1)%2:(ox1+1)%2-2]
                               + image1[1:-1, (ox1+1)%2+1:((ox1+1)%2-1 or None)]
                               + image2[(oy2+1)%2+1:((oy2+1)%2-1 or None), 1:-1]
                               + image2[(oy2+1)%2:(oy2+1)%2-2, 1:-1])/4
    return out
