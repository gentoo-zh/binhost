
root /srv/mirrors;
access_log /var/log/nginx/mirror.log mirror;

limit_conn perip 16;
limit_req zone=reqs burst=100 nodelay;

location ^~ /.well-known/acme-challenge/ {
	root /var/www/acme;
}

# The old raw listing; every directory now lists itself.
location ^~ /_raw/ { return 302 $gz_raw_rel$is_args$args; }

location ^~ /_ls/ {
	alias /srv/pub/;
	log_not_found off;
	autoindex on;
	autoindex_format json;
	include /etc/nginx/conf.d/headers-files.inc;
	add_header Access-Control-Allow-Origin $gz_cors_origin always;
	add_header Vary Origin always;
	add_header Cache-Control "no-cache" always;
	autoindex_localtime off;
	index .no-index;
}

# Directory listings, reached only by the rewrites below; $gz_listing picks one.
# index .no-index keeps a directory holding index.html a listing.
# log_not_found off: a missing directory is the client's 404, not an error to log.
location ^~ /_txt/ {
	internal;
	alias /srv/pub/;
	log_not_found off;
	index .no-index;
	autoindex on;
	autoindex_format xml;
	xslt_stylesheet /etc/nginx/conf.d/listing-txt.xsl;
	include /etc/nginx/conf.d/headers-files.inc;
	include /etc/nginx/conf.d/headers-listing.inc;
}

location ^~ /_html/ {
	internal;
	alias /srv/pub/;
	log_not_found off;
	index .no-index;
	autoindex on;
	autoindex_format html;
	autoindex_exact_size on;
	autoindex_localtime off;
	include /etc/nginx/conf.d/headers-files.inc;
	include /etc/nginx/conf.d/headers-listing.inc;
}

# Browsers go to the file browser on gentoozh.org, in the reader's language.
location ^~ /_web/ {
	internal;
	include /etc/nginx/conf.d/headers-files.inc;
	add_header Vary "Accept, User-Agent, Accept-Language" always;
	add_header Cache-Control "no-cache" always;
	return 302 https://gentoozh.org$gz_prefix/files$gz_path_rel;
}

# The old site pages moved to gentoozh.org; the rewrites below land here with
# the target path. The original query string is kept.
location ^~ /_page/ {
	internal;
	include /etc/nginx/conf.d/headers-files.inc;
	add_header Vary "Accept-Language" always;
	add_header Cache-Control "no-cache" always;
	rewrite ^/_page(?<gz_page>/.*)$ https://gentoozh.org$gz_prefix$gz_page redirect;
}

location ^~ /distfiles/ {
	root /srv/pub;
	include /etc/nginx/conf.d/headers-files.inc;

	gzip off;

	location ~ /$ {
		rewrite ^ /_$gz_listing$uri last;
	}
}

location ^~ /binpkgs/ {
	root /srv/pub;
	include /etc/nginx/conf.d/headers-files.inc;

	location ~ /$ {
		rewrite ^ /_$gz_listing$uri last;
	}

	location ~ \.gpkg\.tar$ {
		root /srv/pub;
		gzip off;
		access_log /var/log/nginx/mirror.log mirror;
		access_log /var/log/nginx/binpkg.log mirror;
		include /etc/nginx/conf.d/headers-files.inc;
	}

	location ~ ^/binpkgs/x86-64/status\.json$ {
		root /srv/pub;
		add_header Cache-Control "no-cache";
		include /etc/nginx/conf.d/headers-files.inc;
		open_file_cache off;
	}

	location ~ /Packages(\.gz)?$ {
		root /srv/pub;
		add_header Cache-Control "public, max-age=300, must-revalidate";
		include /etc/nginx/conf.d/headers-files.inc;
		open_file_cache off;
	}
}

location ^~ /unstable/binpkgs/ {
	root /srv/pub;
	include /etc/nginx/conf.d/headers-files.inc;

	location ~ /$ {
		rewrite ^ /_$gz_listing$uri last;
	}

	location ~ \.gpkg\.tar$ {
		root /srv/pub;
		gzip off;
		access_log /var/log/nginx/mirror.log mirror;
		access_log /var/log/nginx/binpkg.log mirror;
		include /etc/nginx/conf.d/headers-files.inc;
	}

	location ~ ^/unstable/binpkgs/x86-64/status\.json$ {
		root /srv/pub;
		add_header Cache-Control "no-cache";
		include /etc/nginx/conf.d/headers-files.inc;
		open_file_cache off;
	}

	location ~ /Packages(\.gz)?$ {
		root /srv/pub;
		add_header Cache-Control "public, max-age=300, must-revalidate";
		include /etc/nginx/conf.d/headers-files.inc;
		open_file_cache off;
	}
}

location ^~ /gentoo-cjk-kernel/ {
	root /srv/pub;
	include /etc/nginx/conf.d/headers-files.inc;

	gzip off;
	access_log /var/log/nginx/mirror.log mirror;

	location ~ /$ {
		rewrite ^ /_$gz_listing$uri last;
	}
}

location ^~ /gentoo-cjk-livecd/ {
	root /srv/pub;
	include /etc/nginx/conf.d/headers-files.inc;

	gzip off;
	access_log /var/log/nginx/mirror.log mirror;

	location ~ /$ {
		rewrite ^ /_$gz_listing$uri last;
	}
}

location ^~ /gentoo-zh/ {
	rewrite ^/gentoo-zh/(.*)$ /$1 permanent;
}

location = /.health {
	add_header Cache-Control "no-store";
	include /etc/nginx/conf.d/headers-files.inc;
	default_type text/plain;
}

location = /distfiles { return 301 /distfiles/; }
location = /binpkgs { return 301 /binpkgs/; }
location = /unstable { return 301 /unstable/; }
location = /unstable/binpkgs { return 301 /unstable/binpkgs/; }
location = /gentoo-cjk-kernel { return 301 /gentoo-cjk-kernel/; }
location = /gentoo-cjk-livecd { return 301 /gentoo-cjk-livecd/; }
location = /files { return 301 /files/; }
# /files/ is a second name for the root directory, and /files/<dir>/ for
# /<dir>/; a file under /files/ has no second name.
# Named captures: evaluating a regex map such as $gz_listing or $gz_prefix
# resets $1, so a numbered capture after one of them comes out wrong.
location = /files/ { rewrite ^ /_$gz_listing/ last; }
location ^~ /files/ {
	rewrite ^/files(?<gz_dir>/.*/)$ /_$gz_listing$gz_dir last;
	return 404;
}

location = /_app { return 404; }
location = /_app.html { return 404; }
location = /404.html { return 404; }
location ^~ /internal/ { return 404; }
location ^~ /assets/ { return 404; }
# The attribution text moved to the thanks page on gentoozh.org.
location = /assets/NOTICE.txt { rewrite ^ /_page/thanks/ last; }

location ~ ^/~([a-z][a-z0-9_-]*)(/.*)?$ {
	alias /home/$1/public_html$2;
	autoindex on;
	disable_symlinks if_not_owner from=/home;
	include /etc/nginx/conf.d/headers-files.inc;
}

location ~ ^/(about|binpkg-setup|distfiles-setup|faq|iso|logo|overlay|packages|status|thanks)(\.html)?$ {
	rewrite ^/([a-z-]+) /_page/$1/ last;
}
location ~ ^/mirrors?(\.html)?$ { rewrite ^ /_page/mirrorlist/ last; }
location ~ ^/index(\.html)?$ { rewrite ^ /_page/files/ last; }

location = /favicon.ico { return 302 https://gentoozh.org/favicon.ico; }

location = /robots.txt {
	root /srv/mirrors;
	include /etc/nginx/conf.d/headers-files.inc;
}

location = /packages.txt {
	root /srv/mirrors;
	default_type text/plain;
	charset utf-8;
	add_header Cache-Control "no-cache";
	include /etc/nginx/conf.d/headers-files.inc;
	open_file_cache off;
}

location ~* \.json$ {
	add_header Cache-Control "no-cache";
	add_header Access-Control-Allow-Origin $gz_cors_origin always;
	add_header Vary Origin always;
	include /etc/nginx/conf.d/headers-files.inc;
	open_file_cache off;
}

location ~* \.(css|js)$ {
	add_header Cache-Control "public, max-age=31536000, immutable";
	include /etc/nginx/conf.d/headers-files.inc;
	open_file_cache off;
}

location = / { rewrite ^ /_$gz_listing/ last; }

location ~ /$ { rewrite ^ /_$gz_listing$uri last; }

# Gig-OS images were carried until 2026-10. Old links get a real 404 rather than
# the file browser that answers any other unknown directory.
location ^~ /gigos/ { return 404; }

location / {
	add_header Cache-Control "no-cache";
	include /etc/nginx/conf.d/headers-files.inc;
	open_file_cache off;
	try_files $uri $uri.html $uri/index.html $uri/ =404;
}
