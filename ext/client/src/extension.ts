import * as path from "path";
import * as vscode from "vscode";
import { LanguageClient, LanguageClientOptions, ServerOptions, Trace } from "vscode-languageclient/node";

let client: LanguageClient;


export async function activate(context: vscode.ExtensionContext) {
    const outputChannel = vscode.window.createOutputChannel("CDM16 CLIENT")
    outputChannel.show(true);
    outputChannel.appendLine("Output channel working well!");

    // relative path to python server from thin file
    const serverPath = context.asAbsolutePath(
        path.join("..", "server", "src", "server.py") 
    );
    outputChannel.appendLine(`Path to the server ${serverPath}`)

    // launch python server
    const serverOptions: ServerOptions = {
        command: "/home/ruslan/Repos/cdm-devkit/ext/myenv/bin/python3",
        args: [serverPath],
        options: { cwd: path.dirname(serverPath) },
    };

    // client options
    const clientOptions: LanguageClientOptions = {
        documentSelector: [{ scheme: "file", language: "*" }],
        outputChannel: vscode.window.createOutputChannel("CDM16 LSP"),
    };

    // Create and launch client
    client = new LanguageClient(
        "cdm16-lsp",                    // client-id
        "CDM16 Language Server",        // log's name
        serverOptions,
        clientOptions
    );
    client.setTrace(Trace.Verbose);

    // Запускаем клиента
    await client.start();
    outputChannel.appendLine("CDM16 LSP client started!");

    // Добавляем клиента в подписки, чтобы VSCode мог корректно его остановить
    context.subscriptions.push(client);
    vscode.window.showInformationMessage("CDM16 LSP client started!");
}

export async function deactivate(): Promise<void> {
    if (client) {
        await client.stop();
    }
}
