import { toJS, makeAutoObservable } from "mobx";

class Record {
    key;
    value;
    placeholder;

    constructor({ store, id, key, value, placeholder = false }) {
        makeAutoObservable(this);
        this.store = store;
        this.id = id;
        this.key = key;
        this.value = value;
        this.placeholder = placeholder;
    }

    get type() {
        if (typeof this.value === "string") {
            return "string";
        } else if (
            typeof this.value === "number" &&
            this.value === parseInt(this.value, 10)
        ) {
            return "integer";
        } else if (typeof this.value === "number") {
            return "float";
        }
    }

    get error() {
        if (this.key == "") {
            return "Required";
        }

        console.log({k: this.key, id: this.id});

        const dup = this.store.items.find(
            (d) => d.key == this.key && d.id != this.id
        );
        if (dup) {
            return "Not unique!"
        }

        return false;
    }

    update({ key, value, type }) {
        if (key !== undefined) {
            this.key = key;
        }

        if (value !== undefined) {
            this.value = value;
        }

        if (type !== undefined) {
            if (type == "string") {
                if (this.value == undefined || this.value == null) {
                    this.value = "";
                } else {
                    this.value = this.value.toString();
                }
            } else if (type == "integer") {
                this.value = parseInt(this.value);
                if (this.value == undefined || isNaN(this.value)) {
                    this.value = 0;
                }
            } else if (type == "float") {
                this.value = parseFloat(this.value);
                if (this.value == undefined || isNaN(this.value)) {
                    this.value = 0;
                }
            }
        }

        this.placeholder = false;
        this.store.addPlaceholder();
    }
}

export class EditorStore {
    items = [];
    nextId = 0;

    constructor() {
        makeAutoObservable(this);
    }

    load(value) {
        this.items = Object.entries(value.items).map(
            ([key, value], id) => new Record({ store: this, id, key, value })
        );
        this.nextId = this.items.length;
        this.addPlaceholder();
    }

    dump() {
        const items = {};
        this.items.forEach((itm) => {
            items[itm.key] = itm.value;
        });
        return { items: toJS(items) };
    }

    delete(id) {
        this.items = this.items.filter((itm) => itm.id !== id);
        this.addPlaceholder();
    }

    addPlaceholder() {
        if (
            this.items.length == 0 ||
            !this.items[this.items.length - 1].placeholder
        ) {
            this.items.push(
                new Record({ store: this, id: this.nextId, placeholder: true })
            );
            this.nextId++;
        }
    }
}
