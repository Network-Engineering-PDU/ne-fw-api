# Network Engineering Firmware APIs

## Installation
You can use the `pip` command to install this application:

```bash
~/ne-fw-api $ pip install .
```

## ttnedaemon
Network Engineering application daemon. It starts a server attached to the localhost interface, port 8001. It also periodically sends PDU data to the Django server attached to the localhost interface, port 80, using the Django [Network Engineering API](Network-Engineering-PDU/ne/). It also creates a directory, `~/.ne`, to store some files.

```bash
ttnedaemon start|stop|restart
```

## ttnelog
Opens a real time log. To exit, press `CTRL+C`.

```bash
ttnelog
```

## API documentation
Fastapi generates automatic documentation for its APIs, accesible in [http://localhost:8001/docs](http://localhost:8001/docs). From this page you can also try out the different APIs.
