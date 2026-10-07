/*
 * Beeldformaat cloud -> basisstation -> label.
 * Spiegelbeeld van backend/eink_cloud/imageformat.py: wijzigingen altijd in beide doorvoeren.
 */
#ifndef EINK_IMAGE_H
#define EINK_IMAGE_H

#include <stddef.h>
#include <stdint.h>

#define EINK_IMAGE_MAGIC0 'E'
#define EINK_IMAGE_MAGIC1 'I'
#define EINK_IMAGE_VERSION 1
#define EINK_IMAGE_ENCODING_RLE 1
#define EINK_IMAGE_HEADER_SIZE 18

/* Palet-indexen (pixelwaarden). Volgorde ligt vast, zie backend/eink_cloud/displays.py. */
enum eink_color {
	EINK_BLACK = 0,
	EINK_WHITE = 1,
	EINK_RED = 2,
	EINK_YELLOW = 3,
	EINK_BLUE = 4,
	EINK_GREEN = 5,
};

struct eink_image_header {
	uint16_t width;
	uint16_t height;
	uint8_t bits_per_pixel; /* 1, 2 of 4; pixels MSB-eerst, rij voor rij */
	uint8_t palette_id;
	uint32_t crc32;          /* CRC32 (zlib) van de ongecomprimeerde pixeldata */
	uint32_t payload_len;    /* lengte RLE-data na de header */
};

enum eink_image_err {
	EINK_IMAGE_OK = 0,
	EINK_IMAGE_ERR_HEADER = -1,
	EINK_IMAGE_ERR_TRUNCATED = -2,
	EINK_IMAGE_ERR_OVERFLOW = -3,
	EINK_IMAGE_ERR_CRC = -4,
};

int eink_image_parse_header(const uint8_t *buf, size_t len, struct eink_image_header *hdr);

/* Ongecomprimeerde lengte in bytes van de pixeldata. */
size_t eink_image_raw_len(const struct eink_image_header *hdr);

/*
 * Streaming-decoder: roept `sink` aan met stukken gedecodeerde (gepakte) pixeldata,
 * zodat het label het beeld rechtstreeks naar het display-RAM kan schrijven zonder
 * het hele beeld in SRAM te houden. Controleert lengte en CRC32.
 */
typedef int (*eink_image_sink)(void *ctx, const uint8_t *data, size_t len);

int eink_image_decode(const uint8_t *buf, size_t len, eink_image_sink sink, void *ctx,
		      struct eink_image_header *hdr_out);

uint32_t eink_crc32_update(uint32_t crc, const uint8_t *data, size_t len);

#endif /* EINK_IMAGE_H */
