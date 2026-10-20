from django.core.management.base import BaseCommand

from catalog.models import Product
from catalog.seo_content import fill_seo_content


class Command(BaseCommand):
    help = 'Fill empty SEO fields (article, FAQs, meta) of the demo products with sample copy. Never overwrites existing text.'

    def handle(self, *args, **opts):
        filled = sum(fill_seo_content(p) for p in Product.objects.all())
        self.stdout.write(self.style.SUCCESS(f'Filled SEO content for {filled} product(s) (sample copy — review before launch).'))
