#include "eink_image.h"

static uint16_t rd16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static uint32_t rd32(const uint8_t *p)
{
	return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

uint32_t eink_crc32_update(uint32_t crc, const uint8_t *data, size_t len)
{
	/* Bitwise CRC32 (IEEE 802.3, zelfde als zlib); klein in flash. Op nRF kan ook de HW/NCS-crc. */
	crc = ~crc;
	while (len--) {
		crc ^= *data++;
		for (int k = 0; k < 8; k++) {
			crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
		}
	}
	return ~crc;
}

int eink_image_parse_header(const uint8_t *buf, size_t len, struct eink_image_header *hdr)
{
	if (len < EINK_IMAGE_HEADER_SIZE) {
		return EINK_IMAGE_ERR_TRUNCATED;
	}
	if (buf[0] != EINK_IMAGE_MAGIC0 || buf[1] != EINK_IMAGE_MAGIC1 || buf[2] != EINK_IMAGE_VERSION ||
	    buf[3] != EINK_IMAGE_ENCODING_RLE) {
		return EINK_IMAGE_ERR_HEADER;
	}
	hdr->width = rd16(&buf[4]);
	hdr->height = rd16(&buf[6]);
	hdr->bits_per_pixel = buf[8];
	hdr->palette_id = buf[9];
	hdr->crc32 = rd32(&buf[10]);
	hdr->payload_len = rd32(&buf[14]);
	if (hdr->bits_per_pixel != 1 && hdr->bits_per_pixel != 2 && hdr->bits_per_pixel != 4) {
		return EINK_IMAGE_ERR_HEADER;
	}
	if (len < EINK_IMAGE_HEADER_SIZE + (size_t)hdr->payload_len) {
		return EINK_IMAGE_ERR_TRUNCATED;
	}
	return EINK_IMAGE_OK;
}

size_t eink_image_raw_len(const struct eink_image_header *hdr)
{
	return ((size_t)hdr->width * hdr->height * hdr->bits_per_pixel + 7) / 8;
}

int eink_image_decode(const uint8_t *buf, size_t len, eink_image_sink sink, void *ctx,
		      struct eink_image_header *hdr_out)
{
	struct eink_image_header hdr;
	int err = eink_image_parse_header(buf, len, &hdr);
	if (err) {
		return err;
	}
	const uint8_t *p = buf + EINK_IMAGE_HEADER_SIZE;
	const uint8_t *end = p + hdr.payload_len;
	size_t remaining = eink_image_raw_len(&hdr);
	uint32_t crc = 0;
	uint8_t run[128];

	while (p < end) {
		uint8_t c = *p++;
		size_t n = (size_t)(c & 0x7F) + 1;
		const uint8_t *chunk;
		if (n > remaining) {
			return EINK_IMAGE_ERR_OVERFLOW;
		}
		if (c & 0x80) {
			if (p >= end) {
				return EINK_IMAGE_ERR_TRUNCATED;
			}
			for (size_t i = 0; i < n; i++) {
				run[i] = *p;
			}
			p++;
			chunk = run;
		} else {
			if ((size_t)(end - p) < n) {
				return EINK_IMAGE_ERR_TRUNCATED;
			}
			chunk = p;
			p += n;
		}
		crc = eink_crc32_update(crc, chunk, n);
		remaining -= n;
		if (sink && (err = sink(ctx, chunk, n)) != 0) {
			return err;
		}
	}
	if (remaining != 0) {
		return EINK_IMAGE_ERR_TRUNCATED;
	}
	if (crc != hdr.crc32) {
		return EINK_IMAGE_ERR_CRC;
	}
	if (hdr_out) {
		*hdr_out = hdr;
	}
	return EINK_IMAGE_OK;
}
