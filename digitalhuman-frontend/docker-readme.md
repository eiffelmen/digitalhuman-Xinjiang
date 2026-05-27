docker build -t digitalman-web .


docker run --net=host -v $(pwd)/certs:/certs -p 443:443 digitalman-web