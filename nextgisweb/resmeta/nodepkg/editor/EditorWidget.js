import { observer } from "mobx-react-lite";
import {
    Table,
    Tooltip,
    Input,
    InputNumber,
    Select,
    Button,
} from "@nextgisweb/gui/antd";
import DeleteIcon from "@material-icons/svg/delete";
import ErrorIcon from "@material-icons/svg/error";

const { Column } = Table;
const { Option } = Select;

const KeyError = observer(({ record }) => {
    if (record.error) {
        return (
            <Tooltip title={record.error}>
                <span style={{color: "var(--error)"}}><ErrorIcon /></span>
            </Tooltip>
        );
    } else {
        return <span />;
    }
});

const InputKey = observer(({ record }) => {
    return (
        <Input
            value={record.key}
            onChange={(e) => {
                const props = { key: e.target.value };
                if (record.value == undefined) {
                    props.value = "";
                };
                record.update(props);
            }}
            suffix={<KeyError record={record}/>}
            bordered={false}
            placeholder={
                record.placeholder ? "Type here to add an item..." : undefined
            }
        />
    );
});

const InputValue = observer(({ record }) => {
    if (record.type === "string") {
        return (
            <Input
                value={record.value}
                onChange={(e) => {
                    record.update({ value: e.target.value });
                }}
                bordered={false}
            />
        );
    } else if (record.type === "number") {
        return (
            <InputNumber
                value={record.value}
                controls={false}
                onChange={(newValue) => {
                    record.update({ value: newValue });
                }}
                bordered={false}
            />
        );
    }

    return <></>;
});

const SelectType = observer(({ record }) => {
    if (record.placeholder) {
        return <></>;
    }

    return (
        <Select
            value={record.type}
            onChange={(value) => {
                record.update({ type: value });
            }}
            bordered={false}
            style={{ width: "100%" }}
        >
            <Option value="string">String</Option>
            <Option value="number">Number</Option>
        </Select>
    );
});

export const EditorWidget = observer(({ store }) => {
    return (
        <Table
            rowKey="id"
            dataSource={store.items.slice()}
            pagination={false}
            size="small"
        >
            <Column
                title="Key"
                dataIndex="key"
                render={(_, record) => {
                    return <InputKey record={record} />;
                }}
            />
            <Column
                title="Type"
                dataIndex="type"
                render={(_, record) => {
                    return <SelectType record={record} />;
                }}
            />
            <Column
                title="Value"
                dataIndex="value"
                render={(_, record) => {
                    return <InputValue record={record} />;
                }}
            />
            <Column
                render={(_, record) => {
                    if (!record.placeholder) {
                        return (
                            <Button
                                shape="circle"
                                icon={<DeleteIcon />}
                                onClick={() => store.delete(record.id)}
                            />
                        );
                    }

                    return <></>;
                }}
            />
        </Table>
    );
});
