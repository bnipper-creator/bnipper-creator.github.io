SLUG ?= wayfarers-compass
BOOK ?= fixtures/$(SLUG).epub

.PHONY: all fixture digest verify roundtrip query clean

all: digest verify roundtrip

fixture:
	python3 tools/make_fixture.py

digest:
	python3 src/digest.py $(BOOK) --slug $(SLUG)

verify:
	python3 src/verify.py library/$(SLUG)

roundtrip:
	python3 src/roundtrip.py library/$(SLUG)

query:
	python3 tools/query.py library/$(SLUG) chapter "Chapter 3. On Storms"
	python3 tools/query.py library/$(SLUG) reference 3:2
	python3 tools/query.py library/$(SLUG) topic needle

clean:
	rm -rf library/$(SLUG)
