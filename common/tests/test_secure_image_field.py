from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image
from rest_framework import serializers

from common.api.fields import SecureImageField


class SecureImageSerializer(serializers.Serializer):
    image = SecureImageField()


def image_upload(*, name='image.png', size=(1, 1), image_format='PNG', frames=1):
    buffer = BytesIO()
    images = [Image.new('1', size, color=index % 2) for index in range(frames)]
    images[0].save(
        buffer,
        format=image_format,
        save_all=frames > 1,
        append_images=images[1:],
    )
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=f'image/{image_format.lower()}')


class SecureImageFieldTests(SimpleTestCase):
    def test_accepts_small_static_png(self):
        serializer = SecureImageSerializer(data={'image': image_upload()})
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_rejects_encoded_file_over_limit_before_decoding(self):
        upload = SimpleUploadedFile('large.png', b'x' * (5 * 1024 * 1024 + 1), content_type='image/png')
        serializer = SecureImageSerializer(data={'image': upload})

        self.assertFalse(serializer.is_valid())
        self.assertIn('5 MiB', str(serializer.errors['image'][0]))

    def test_rejects_decompression_bomb_by_decoded_pixel_count(self):
        serializer = SecureImageSerializer(data={'image': image_upload(size=(5000, 5000))})

        self.assertFalse(serializer.is_valid())
        self.assertIn('megapixel', str(serializer.errors['image'][0]))

    def test_rejects_animated_and_unsupported_image_formats(self):
        animated = SecureImageSerializer(
            data={'image': image_upload(name='animated.webp', image_format='WEBP', frames=2)}
        )
        gif = SecureImageSerializer(data={'image': image_upload(name='image.gif', image_format='GIF')})

        self.assertFalse(animated.is_valid())
        self.assertIn('Animated', str(animated.errors['image'][0]))
        self.assertFalse(gif.is_valid())
        self.assertIn('PNG', str(gif.errors['image'][0]))
