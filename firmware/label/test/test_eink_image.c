/* Host-test: decodeert een door de backend gemaakt frame.  Zie firmware/README.md. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../src/eink_image.h"

struct out { uint8_t *buf; size_t len; };

static int sink(void *ctx, const uint8_t *data, size_t len)
{
	struct out *o = ctx;
	memcpy(o->buf + o->len, data, len);
	o->len += len;
	return 0;
}

static uint8_t *read_file(const char *path, size_t *len)
{
	FILE *f = fopen(path, "rb");
	if (!f) { perror(path); exit(2); }
	fseek(f, 0, SEEK_END);
	*len = (size_t)ftell(f);
	rewind(f);
	uint8_t *buf = malloc(*len);
	if (fread(buf, 1, *len, f) != *len) { exit(2); }
	fclose(f);
	return buf;
}

int main(int argc, char **argv)
{
	if (argc != 3) {
		fprintf(stderr, "gebruik: %s frame.bin raw.bin\n", argv[0]);
		return 2;
	}
	size_t flen, rlen;
	uint8_t *frame = read_file(argv[1], &flen);
	uint8_t *raw = read_file(argv[2], &rlen);
	struct out o = { malloc(rlen + 128), 0 };
	struct eink_image_header hdr;

	int err = eink_image_decode(frame, flen, sink, &o, &hdr);
	if (err || o.len != rlen || memcmp(o.buf, raw, rlen) != 0) {
		fprintf(stderr, "FOUT: err=%d len=%zu verwacht=%zu\n", err, o.len, rlen);
		return 1;
	}
	frame[flen - 1] ^= 0xFF; /* corruptie moet gedetecteerd worden */
	o.len = 0;
	if (eink_image_decode(frame, flen, sink, &o, NULL) == EINK_IMAGE_OK) {
		fprintf(stderr, "FOUT: corrupt frame niet gedetecteerd\n");
		return 1;
	}
	printf("OK %ux%u bpp=%u crc=%08x\n", hdr.width, hdr.height, hdr.bits_per_pixel, (unsigned)hdr.crc32);
	return 0;
}
