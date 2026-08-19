from PIL import Image, UnidentifiedImageError
from rest_framework import serializers


class SecureImageField(serializers.ImageField):
    default_error_messages = {
        **serializers.ImageField.default_error_messages,
        'file_too_large': 'Image file exceeds the 5 MiB upload limit.',
        'pixel_limit': 'Image dimensions exceed the 20 megapixel decoded limit.',
        'dimension_limit': 'Image width or height exceeds 8192 pixels.',
        'format_denied': 'Only PNG, JPEG and WebP images are supported.',
        'animated_denied': 'Animated images are not supported.',
        'invalid_image': 'Upload a valid image.',
    }

    def __init__(
        self,
        *args,
        max_bytes=5 * 1024 * 1024,
        max_pixels=20_000_000,
        max_dimension=8192,
        allowed_formats=('PNG', 'JPEG', 'WEBP'),
        **kwargs,
    ):
        self.max_bytes = int(max_bytes)
        self.max_pixels = int(max_pixels)
        self.max_dimension = int(max_dimension)
        self.allowed_formats = frozenset(str(value).upper() for value in allowed_formats)
        super().__init__(*args, **kwargs)

    def to_internal_value(self, data):
        size = getattr(data, 'size', None)
        if not isinstance(size, int) or size < 1 or size > self.max_bytes:
            self.fail('file_too_large' if isinstance(size, int) and size > self.max_bytes else 'invalid_image')

        uploaded = super().to_internal_value(data)
        try:
            uploaded.seek(0)
            with Image.open(uploaded) as image:
                width, height = image.size
                image_format = str(image.format or '').upper()
                if width < 1 or height < 1:
                    self.fail('invalid_image')
                if width > self.max_dimension or height > self.max_dimension:
                    self.fail('dimension_limit')
                if width * height > self.max_pixels:
                    self.fail('pixel_limit')
                if image_format not in self.allowed_formats:
                    self.fail('format_denied')
                if getattr(image, 'is_animated', False) or int(getattr(image, 'n_frames', 1)) != 1:
                    self.fail('animated_denied')
                image.verify()
        except serializers.ValidationError:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning, UnidentifiedImageError, OSError, ValueError):
            self.fail('invalid_image')
        finally:
            try:
                uploaded.seek(0)
            except (AttributeError, OSError):
                pass
        return uploaded
