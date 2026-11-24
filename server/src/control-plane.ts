import { startApi } from "./api.js";
import { startGateway } from "./gateway.js";
import { startWorker } from "./worker.js";

// Status, enrollments, and commands currently live in one shared Store.
startApi();
startGateway();
startWorker();
